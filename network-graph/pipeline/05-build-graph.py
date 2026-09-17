#!/usr/bin/env python3
"""Verify overlaps from the collected profiles and emit the graph data file.

For every (partner, colleague) pair suggested by the searches, the overlap is
recomputed from the colleague's OWN experience entries. Pairs without a
genuine same-company date overlap with the partner's window are discarded;
this is also the safety net for the search/filter fallback.

Edge weight in [0,1]:
  0.35 * min(overlap_years / 4, 1)
  0.20 * seniority_proximity   (1.0 same band, 0.6 adjacent, 0.2 otherwise)
  0.15 * function_match        (keyword-set Jaccard of the overlap titles)
  0.15 * recency               (1.0 within 5 years, decays to 0.2 at 25)
  0.15 * company_size_inverse  (1.0 under 500, 0.5 to 10k, 0.2 above)
Tiers: strong >= 0.6, possible 0.3 to 0.6, dropped below 0.3. "confirmed"
is reserved for fund-to-partner edges and partners' current board seats.

Writes NETWORK_OUT (default <work>/network-data.js). Free: no API calls.

Run: python3 05-build-graph.py
"""

import glob
import json
import os
import re
from datetime import date

import coresignal as cs

OUT = os.environ.get("NETWORK_OUT", os.path.join(cs.WORK, "network-data.js"))

STRONG = 0.6
POSSIBLE = 0.3


def fmt_year(y):
    yy, mm = divmod(int(round(y * 12)), 12)
    return "%04d-%02d" % (yy, mm + 1)


def seniority_band(title):
    t = str(title).lower()
    if re.search(r"\b(evp|svp|avp|vp)\b|vice president|general manager", t):
        return 2
    if re.search(r"\bchief\b|\b(ceo|cio|coo|cfo|cto|cmo|chro)\b|\bpresident\b"
                 r"|\bfounder\b|\bowner\b", t):
        return 3
    if re.search(r"\bdirector\b|\bhead of\b", t):
        return 1
    return 0


def seniority_proximity(title_a, title_b):
    diff = abs(seniority_band(title_a) - seniority_band(title_b))
    return 1.0 if diff == 0 else 0.6 if diff == 1 else 0.2


def function_match(title_a, title_b):
    a, b = cs.title_keywords(title_a), cs.title_keywords(title_b)
    union = a | b
    if not union:
        return 0.5  # neither title carries a function word; neutral
    return len(a & b) / len(union)


def recency_score(overlap_end_year):
    since = max(0.0, cs.now_year() - overlap_end_year)
    if since <= 5:
        return 1.0
    if since >= 25:
        return 0.2
    return 1.0 - 0.8 * (since - 5) / 20.0


def size_bucket(n):
    return 1.0 if n < 500 else 0.5 if n <= 10000 else 0.2


def company_size_score(matched_entries, company, companies):
    # employee count from the profile when present, else the config list
    for e in matched_entries:
        raw = e.get("raw") or {}
        for key in ("company_employees_count", "company_employee_count", "company_size"):
            m = re.search(r"\d+", str(raw.get(key) or "").replace(",", ""))
            if m:
                return size_bucket(int(m.group()))
    for c in companies:
        if c.get("size") and cs.same_company(company, c["name"]):
            return size_bucket(c["size"])
    return 0.5


def merged_total(spans):
    spans = sorted(spans)
    total = 0.0
    cur_lo, cur_hi = spans[0]
    for lo, hi in spans[1:]:
        if lo > cur_hi:
            total += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    return total + (cur_hi - cur_lo)


def overlap_with_window(entries, company, w_from_y, w_to_y):
    """Genuine overlap of a person's stints at company with the partner window."""
    spans, matched = [], []
    for e in entries:
        if not cs.same_company(e["company"], company):
            continue
        s = cs.parse_year(e["date_from"])
        if s is None:
            continue
        t = cs.parse_year(e["date_to"])
        if t is None:
            t = cs.now_year()
        lo, hi = max(s, w_from_y), min(t, w_to_y)
        if hi - lo > 0.01:
            spans.append((lo, hi))
            matched.append((hi, e))
    if not spans:
        return None
    latest = max(matched, key=lambda x: x[0])[1]
    return {
        "years": merged_total(spans),
        "start": min(lo for lo, hi in spans),
        "end": max(hi for lo, hi in spans),
        "title": latest["title"],
        "entries": [m[1] for m in matched],
    }


def current_role(entries, board_re):
    """The entry with null date_to (a job over a board seat), else the latest date_to."""
    current = [e for e in entries if not e["date_to"]]
    if current:
        pick = max(current, key=lambda e: (not board_re.search(e["title"]),
                                           cs.parse_year(e["date_from"]) or 0.0))
    else:
        dated = [e for e in entries if cs.parse_year(e["date_to"]) is not None]
        pick = (max(dated, key=lambda e: cs.parse_year(e["date_to"]))
                if dated else (entries[0] if entries else None))
    return (pick["title"], pick["company"]) if pick else ("", "")


def linkedin_url(profile):
    for key in ("linkedin_url", "url", "canonical_url", "profile_url"):
        v = profile.get(key)
        if isinstance(v, str) and "linkedin.com" in v:
            return v
    return ""


def location_of(profile):
    return (profile.get("location_full") or profile.get("location") or "").strip()


def main():
    config = cs.load_config()
    fund = config["fund"]
    partners = config["partners"]
    companies = config.get("companies", [])
    board_re = re.compile(config.get("board_title_regex") or r"\bboard\b", re.I)

    missing = [p["shorthand"] for p in partners if not os.path.exists(
        os.path.join(cs.COLLECTS, "op-%s.json" % p["shorthand"]))]
    if missing:
        raise SystemExit("No collects for: %s. Run 01-collect-partners.py first."
                         % ", ".join(missing))

    op_profiles = {}
    for p in partners:
        with open(os.path.join(cs.COLLECTS, "op-%s.json" % p["shorthand"])) as f:
            op_profiles[p["shorthand"]] = json.load(f)

    person_cache = {}

    def person(cid):
        if cid not in person_cache:
            path = os.path.join(cs.COLLECTS, "person-%d.json" % cid)
            if not os.path.exists(path):
                return None
            with open(path) as f:
                person_cache[cid] = json.load(f)
        return person_cache[cid]

    # verify every suggested pair against the colleague's own history
    best, considered, discarded = {}, set(), 0
    for spath in sorted(glob.glob(os.path.join(cs.SEARCHES, "*.json"))):
        with open(spath) as f:
            s = json.load(f)
        op_short = s["op"]
        if op_short not in op_profiles:
            print("warning: %s references unknown partner %s, skipped"
                  % (os.path.basename(spath), op_short))
            continue
        w_from_y = cs.parse_year(s["window"].get("date_from"))
        if w_from_y is None:
            print("warning: %s has no window start, skipped" % os.path.basename(spath))
            continue
        w_to_y = cs.parse_year(s["window"].get("date_to")) or cs.now_year()
        op_title = s.get("op_title") or ""
        for cid in s.get("tierA", []) + s.get("tierB", []):
            profile = person(cid)
            if profile is None:
                continue
            considered.add((op_short, cid))
            ov = overlap_with_window(cs.experience_entries(profile),
                                     s["company"], w_from_y, w_to_y)
            if ov is None:
                discarded += 1
                continue
            weight = (0.35 * min(ov["years"] / 4.0, 1.0)
                      + 0.20 * seniority_proximity(op_title, ov["title"])
                      + 0.15 * function_match(op_title, ov["title"])
                      + 0.15 * recency_score(ov["end"])
                      + 0.15 * company_size_score(ov["entries"], s["company"], companies))
            prev = best.get((op_short, cid))
            if prev is None or weight > prev["weight"]:
                best[(op_short, cid)] = {
                    "weight": weight,
                    "company": s["company"],
                    "overlap_years": round(ov["years"], 1),
                    "window": "%s to %s" % (fmt_year(ov["start"]), fmt_year(ov["end"])),
                }

    # a search window can return a partner under their numeric id; partners
    # are already nodes, so those never become colleagues
    op_ids = {prof.get("id") for prof in op_profiles.values()}
    kept = {k: v for k, v in best.items() if v["weight"] >= POSSIBLE and k[1] not in op_ids}
    dropped = sum(1 for v in best.values() if v["weight"] < POSSIBLE)

    as_of = date.today().isoformat()
    nodes = [{
        "id": fund["id"], "name": fund["name"], "kind": "fund", "tier": "confirmed",
        "title": fund.get("title", ""), "employer": fund["name"],
        "location": fund.get("location", ""), "as_of": as_of, "linkedin": "",
    }]
    edges, seats = [], []
    employer_index, display_of = {}, {}

    def add_employer(e, node_id):
        # merge spelling variants by provider company_id when present; the
        # shortest spelling wins as the display name
        name = e["company"]
        if not name:
            return
        cid = (e.get("raw") or {}).get("company_id")
        key = ("id", cid) if cid else ("nm", cs.norm_company(name))
        if not key[1]:
            return
        clean = " ".join(str(name).split())
        disp = display_of.get(key)
        if disp is None:
            display_of[key] = disp = clean
        elif len(clean) < len(disp):
            if disp in employer_index:
                merged = employer_index.pop(disp)
                for x in employer_index.setdefault(clean, []):
                    if x not in merged:
                        merged.append(x)
                employer_index[clean] = merged
            display_of[key] = disp = clean
        bucket = employer_index.setdefault(disp, [])
        if node_id not in bucket:
            bucket.append(node_id)

    for p in partners:
        short = p["shorthand"]
        entries = cs.experience_entries(op_profiles[short])
        title, employer = current_role(entries, board_re)
        nodes.append({
            "id": short, "name": p["name"], "kind": "op", "tier": "confirmed",
            "title": title, "employer": employer,
            "location": location_of(op_profiles[short]), "as_of": as_of,
            "linkedin": p.get("linkedin", ""),
        })
        seen_seats = set()
        for e in entries:
            add_employer(e, short)
            # a current board or advisory seat is a confirmed present-day door
            if (not e["date_to"] and board_re.search(e["title"])
                    and not cs.same_company(e["company"], fund["name"])
                    and e["company"].lower() not in seen_seats):
                seen_seats.add(e["company"].lower())
                seats.append({
                    "advisor_id": short, "advisor_name": p["name"],
                    "company": e["company"], "title": e["title"],
                    "since": (e["date_from"] or "")[:4] or None,
                })
        edges.append({
            "source": fund["id"], "target": short, "weight": 1.0, "tier": "confirmed",
            "basis": {"company": fund["name"], "overlap_years": None,
                      "window": "current engagement"},
        })

    colleague_tier = {}
    for (op_short, cid), edge in sorted(kept.items(), key=lambda kv: -kv[1]["weight"]):
        tier = "strong" if edge["weight"] >= STRONG else "possible"
        colleague_tier.setdefault(cid, tier)  # heaviest edge sets the node tier
        edges.append({
            "source": op_short, "target": "cs-%d" % cid,
            "weight": round(edge["weight"], 3), "tier": tier,
            "basis": {"company": edge["company"],
                      "overlap_years": edge["overlap_years"],
                      "window": edge["window"]},
        })

    for cid, tier in colleague_tier.items():
        profile = person(cid)
        entries = cs.experience_entries(profile)
        title, employer = current_role(entries, board_re)
        node_id = "cs-%d" % cid
        nodes.append({
            "id": node_id, "name": cs.profile_name(profile),
            "kind": "colleague", "tier": tier, "title": title,
            "employer": employer, "location": location_of(profile),
            "as_of": as_of, "linkedin": linkedin_url(profile),
        })
        for e in entries:
            add_employer(e, node_id)

    data = {
        "generatedAt": as_of,
        "nodes": nodes,
        "edges": edges,
        "employerIndex": employer_index,
        "advisorySeats": seats,
        "companies": [{k: c.get(k) for k in ("name", "domain", "sector")}
                      for c in companies],
    }
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    with open(OUT, "w") as f:
        f.write("// Generated by pipeline/05-build-graph.py on %s. Do not hand-edit.\n"
                "window.NETWORK_DATA = %s;\n"
                % (as_of, json.dumps(data, indent=1, ensure_ascii=False)))

    n_col = sum(1 for n in nodes if n["kind"] == "colleague")
    n_strong = sum(1 for e in edges if e["tier"] == "strong")
    print("Wrote %s" % OUT)
    print("  nodes: 1 fund, %d partners, %d colleagues" % (len(partners), n_col))
    print("  edges: %d confirmed, %d strong, %d possible; %d board seats"
          % (len(partners), n_strong, len(edges) - len(partners) - n_strong, len(seats)))
    print("  pairs considered: %d, no genuine overlap: %d, below 0.3: %d"
          % (len(considered), discarded, dropped))


if __name__ == "__main__":
    main()
