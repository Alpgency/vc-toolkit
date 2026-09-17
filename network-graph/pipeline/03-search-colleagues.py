#!/usr/bin/env python3
"""Free tiered colleague searches for every kept target window.

Tier A: senior titles (Chief, President, EVP, SVP, VP, General Manager, CIO,
COO, CFO) whose stint sits fully inside the partner's window at that company.
Tier B: Director and above with roughly three months of overlap. Exact
overlap is recomputed from the full profile in 05, which discards false joins.

Consideration is capped at CAP ids per window. On overflow the query is
tightened first by geography (config geo_terms plus hq_city for the company),
then by function keywords from the partner's own title. A tightening stage
that drops below MIN_KEEP ids is discarded in favor of the wider set.

Uses es_dsl; falls back to search/filter flat params if the plan lacks it
(403/404). Searches cost 0 credits.

Run: python3 03-search-colleagues.py
"""

import json
import os
from datetime import date

import coresignal as cs

CAP = 300
MIN_KEEP = 30

SENIOR_TITLES = ["Chief", "President", "EVP", "SVP", "VP",
                 "General Manager", "CIO", "COO", "CFO"]
TIER_B_TITLES = SENIOR_TITLES + ["Director"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

STATE = {"es_dsl": True}


def shift_months(datestr, months):
    y = cs.parse_year(datestr)
    if y is None:
        return None
    yy, mm = divmod(int(round(y * 12)) + months, 12)
    return "%04d-%02d-01" % (yy, mm + 1)


def es_date(iso):
    # the date fields parse only "MMMM uuuu" or "uuuu"
    if not iso:
        return None
    y, m = str(iso)[:7].split("-")
    return "%s %s" % (MONTHS[int(m) - 1], y)


def title_clause(titles):
    return {"bool": {
        "should": [{"match_phrase": {"experience.title": t}} for t in titles],
        "minimum_should_match": 1,
    }}


def dsl_body(company, w_from, w_to, titles, mode, geo=None, funcs=None):
    must = [{"match_phrase": {"experience.company_name": company}},
            title_clause(titles)]
    end = w_to or date.today().isoformat()
    if mode == "inside":
        if w_from:
            must.append({"range": {"experience.date_from": {"gte": es_date(w_from)}}})
        if w_to:
            must.append({"range": {"experience.date_to": {"lte": es_date(w_to)}}})
    else:
        lo = shift_months(end, -3)
        if lo:
            must.append({"range": {"experience.date_from": {"lte": es_date(lo)}}})
        hi = shift_months(w_from, 3) if w_from else None
        if hi:
            # null date_to means a current stint, which also overlaps
            must.append({"bool": {"should": [
                {"range": {"experience.date_to": {"gte": es_date(hi)}}},
                {"bool": {"must_not": {"exists": {"field": "experience.date_to"}}}},
            ], "minimum_should_match": 1}})
    if funcs:
        must.append({"bool": {
            "should": [{"match": {"experience.title": w}} for w in sorted(funcs)],
            "minimum_should_match": 1,
        }})
    query = {"nested": {"path": "experience", "query": {"bool": {"must": must}}}}
    if geo:
        query = {"bool": {"must": [
            query,
            {"bool": {"should": [{"match": {"location": g}} for g in geo],
                      "minimum_should_match": 1}},
        ]}}
    # the endpoint rejects a top-level "size"; CAP is applied to the id list
    return {"query": query}


def filter_params(company, w_from, w_to, titles, geo=None):
    # flat params cannot AND function keywords into the title, so the filter
    # engine only tightens by geography; 05 discards false joins anyway
    p = {
        "experience_company_name": company,
        "experience_title": " OR ".join("(%s)" % t for t in titles),
    }
    if w_from:
        p["experience_date_from"] = str(w_from)[:4]
    p["experience_date_to"] = str(w_to)[:4] if w_to else str(date.today().year)
    if geo:
        p["location"] = " OR ".join("(%s)" % g for g in geo)
    return p


def run_query(company, w_from, w_to, titles, mode, geo, funcs):
    body = dsl_body(company, w_from, w_to, titles, mode, geo, funcs)
    params = filter_params(company, w_from, w_to, titles, geo)
    if STATE["es_dsl"]:
        try:
            return cs.ids_from(cs.search_es_dsl(body)), "es_dsl", body
        except cs.ApiError as e:
            if e.status in (403, 404):
                STATE["es_dsl"] = False
                print("  note: es_dsl unavailable (HTTP %d); using search/filter"
                      % e.status)
            else:
                raise
    return cs.ids_from(cs.search_filter(params)), "filter", params


def consider(target, config):
    company = target["company"]
    w_from, w_to = target.get("date_from"), target.get("date_to")
    geo = list(config.get("geo_terms", []))
    hq = config.get("hq_city", {}).get(cs.norm_company(company))
    if hq and hq not in geo:
        geo.append(hq)
    funcs = cs.title_keywords(target.get("op_title") or "")

    plans = [("base", None, None)]
    if geo:
        plans.append(("geo", geo, None))
    if funcs:
        plans.append(("function", geo or None, funcs))

    best = None
    for label, g, f in plans:
        a, eng, qa = run_query(company, w_from, w_to, SENIOR_TITLES, "inside", g, f)
        b, eng, qb = run_query(company, w_from, w_to, TIER_B_TITLES, "overlap", g, f)
        a_set = set(a)
        b = [i for i in b if i not in a_set]
        total = len(a) + len(b)
        result = {"tierA": a, "tierB": b, "total": total,
                  "query_used": {"engine": eng, "stage": label,
                                 "tierA": qa, "tierB": qb}}
        if total < MIN_KEEP and best is not None:
            print("    stage %s returned %d, too tight; keeping the wider set"
                  % (label, total))
            break
        best = result
        if total <= CAP:
            break
        print("    stage %s overflows the cap with %d ids; tightening" % (label, total))
    if best["total"] > CAP:
        best["tierA"] = best["tierA"][:CAP]
        best["tierB"] = best["tierB"][:max(0, CAP - len(best["tierA"]))]
        print("    still over %d after tightening; truncated" % CAP)
    return best


def main():
    if not os.path.exists(cs.TARGETS):
        raise SystemExit("targets.json missing. Run 02-derive-targets.py first.")
    config = cs.load_config()
    with open(cs.TARGETS) as f:
        data = json.load(f)
    os.makedirs(cs.SEARCHES, exist_ok=True)

    written = skipped = 0
    for short, entry in data["ops"].items():
        print("\n%s (%s)" % (entry["name"], short))
        for t in entry["targets"]:
            if not t.get("keep"):
                print("  keep=false, skipping: %s" % t["company"])
                continue
            out_path = os.path.join(cs.SEARCHES,
                                    "%s-%s.json" % (short, cs.slug(t["company"])))
            if os.path.exists(out_path):
                print("  already searched, skipping (delete file to redo): %s"
                      % t["company"])
                skipped += 1
                continue
            print("  searching %s (%s to %s)"
                  % (t["company"], t.get("date_from"), t.get("date_to") or "now"))
            r = consider(t, config)
            with open(out_path, "w") as f:
                json.dump({
                    "op": short,
                    "company": t["company"],
                    "op_title": t.get("op_title") or "",
                    "window": {"date_from": t.get("date_from"),
                               "date_to": t.get("date_to")},
                    "tierA": r["tierA"],
                    "tierB": r["tierB"],
                    "query_used": r["query_used"],
                }, f, indent=2)
            print("    tierA %d, tierB %d" % (len(r["tierA"]), len(r["tierB"])))
            written += 1

    print("\n%d search files written, %d skipped. Searches cost 0 credits."
          % (written, skipped))
    print("Next: python3 04-rank-and-collect.py")


if __name__ == "__main__":
    main()
