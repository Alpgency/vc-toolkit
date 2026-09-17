#!/usr/bin/env python3
"""Free enumeration of the board orbit for every board window.

SEARCH-ONLY by construction: this module has no collect call, so it cannot
spend a single credit no matter how it is run. It counts and lists candidate
ids per board window; enrichment (collect) is a separate, budgeted step in
its own run.

Usage:
  CORESIGNAL_API_KEY=... python3 engine/etl/search_board_colleagues.py \
      board-windows.json > board-candidates.json
"""

import json
import os
import sys
import urllib.request
from datetime import date

BASE = "https://api.coresignal.com/cdapi/v2/employee_base"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# who sits around a board: fellow governors and the exec team they oversee
TITLES = ["Board", "Director", "Chief", "President", "Founder",
          "CEO", "CFO", "COO", "Advisor"]
CAP = 100

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def es_date(iso):
    if not iso:
        return None
    y, m = str(iso)[:7].split("-")
    return "%s %s" % (MONTHS[int(m) - 1], y)


def search(body):
    req = urllib.request.Request(
        BASE + "/search/es_dsl",
        data=json.dumps(body).encode(),
        headers={"apikey": os.environ["CORESIGNAL_API_KEY"],
                 "User-Agent": UA, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def ids_from(result):
    if isinstance(result, list):
        return [int(x) for x in result if str(x).isdigit()]
    return []


def body_for(w):
    must = [{"match_phrase": {"experience.company_name": w["company"]}},
            {"bool": {"should": [{"match_phrase": {"experience.title": t}}
                                 for t in TITLES],
                      "minimum_should_match": 1}}]
    # overlap: their stint must start before the window ends and either end
    # after the window starts or still be running
    end = w.get("to") or date.today().strftime("%Y-%m")
    must.append({"range": {"experience.date_from": {"lte": es_date(end)}}})
    if w.get("from"):
        must.append({"bool": {"should": [
            {"range": {"experience.date_to": {"gte": es_date(w["from"])}}},
            {"bool": {"must_not": {"exists": {"field": "experience.date_to"}}}},
        ], "minimum_should_match": 1}})
    return {"query": {"nested": {"path": "experience",
                                 "query": {"bool": {"must": must}}}}}


def main(path):
    windows = json.load(open(path))["windows"]
    out = []
    for w in windows:
        try:
            ids = ids_from(search(body_for(w)))
        except Exception as e:  # keep sweeping; report the miss
            out.append({**w, "error": str(e)})
            continue
        out.append({**w, "candidates": len(ids), "ids": ids[:CAP]})
        print("%-28s %-24s %4d candidates" %
              (w["advisor_name"][:27], w["company"][:23], len(ids)),
              file=sys.stderr)
    total = sum(r.get("candidates", 0) for r in out)
    print("total candidate slots: %d (each costs one collect to enrich)"
          % total, file=sys.stderr)
    json.dump({"windows": out, "total_candidates": total}, sys.stdout, indent=2)


if __name__ == "__main__":
    main(sys.argv[1])
