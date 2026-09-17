#!/usr/bin/env python3
"""Derive per-partner target company windows from the collected profiles.

Merges same-company stints into one window, drops stints under 12 months,
sorts windows whose company matches a config priority keyword first, and
writes <work>/targets.json.

REVIEW CHECKPOINT: hand-review targets.json and flip "keep": false on any
window that should not be searched, then run 03. Free: no API calls.

Run: python3 02-derive-targets.py
"""

import json
import os
from datetime import date

import coresignal as cs

MIN_MONTHS = 12


def merge_windows(entries):
    """One window per company: earliest start to latest end, latest title."""
    groups = {}
    for e in entries:
        if e["company"]:
            groups.setdefault(cs.norm_company(e["company"]), []).append(e)
    out = []
    for group in groups.values():
        froms = sorted((e["date_from"] for e in group if e["date_from"]),
                       key=cs.parse_year)
        if any(not e["date_to"] for e in group):
            date_to = None
        else:
            tos = sorted((e["date_to"] for e in group if e["date_to"]),
                         key=cs.parse_year)
            date_to = tos[-1] if tos else None
        latest = max(group, key=lambda e: cs.parse_year(e["date_from"]) or 0.0)
        out.append({
            "company": group[0]["company"],
            "date_from": froms[0] if froms else None,
            "date_to": date_to,
            "op_title": latest["title"],
        })
    return out


def main():
    config = cs.load_config()
    keywords = [k.lower() for k in config.get("priority_keywords", [])]
    fund = config["fund"]["name"]

    out = {
        "generated_at": date.today().isoformat(),
        "note": "hand-review the keep flags, then run 03-search-colleagues.py",
        "ops": {},
    }
    for p in config["partners"]:
        path = os.path.join(cs.COLLECTS, "op-%s.json" % p["shorthand"])
        if not os.path.exists(path):
            raise SystemExit("Missing %s. Run 01-collect-partners.py first." % path)
        with open(path) as f:
            profile = json.load(f)
        targets = []
        for w in merge_windows(cs.experience_entries(profile)):
            if cs.same_company(w["company"], fund):
                continue
            years = cs.span_years(w["date_from"], w["date_to"])
            if years is not None and years * 12 < MIN_MONTHS:
                continue
            targets.append({
                "company": w["company"],
                "date_from": w["date_from"],
                "date_to": w["date_to"],
                "op_title": w["op_title"],
                "years": round(years, 1) if years is not None else None,
                "priority": any(k in w["company"].lower() for k in keywords),
                "keep": True,
            })
        targets.sort(key=lambda t: (not t["priority"], -(t["years"] or 0.0)))
        out["ops"][p["shorthand"]] = {"name": p["name"], "targets": targets}
        print("  %-24s %2d target windows" % (p["name"], len(targets)))

    with open(cs.TARGETS, "w") as f:
        json.dump(out, f, indent=2)
    print("\nWrote %s" % cs.TARGETS)
    print("REVIEW CHECKPOINT: flip \"keep\": false on windows you do not want")
    print("searched. Then run: python3 03-search-colleagues.py")


if __name__ == "__main__":
    main()
