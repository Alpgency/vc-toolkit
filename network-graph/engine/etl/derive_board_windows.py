#!/usr/bin/env python3
"""Derive board and advisory windows from the partners' collected profiles.

Board seats reach relationships co-tenure never sees: fellow directors and
the leadership orbit of companies a partner GOVERNS rather than worked at.
Education windows are deliberately excluded.

Usage:
  python3 engine/etl/derive_board_windows.py <collects-dir> "<fund name>" \
      > board-windows.json
Reads only op-*.json (the partners). Skips seats at the fund itself.
Dedupes multi-source repeats.
"""

import glob
import json
import os
import re
import sys

BOARD = re.compile(
    r"\b(board|trustee|non.?executive director|advisor|advisory)\b", re.I)

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def norm_date(v):
    """'January 2025' | '2025' | None -> 'YYYY-MM' | None"""
    if not v:
        return None
    s = str(v).strip()
    m = re.match(r"([A-Z][a-z]+) (\d{4})$", s)
    if m and m.group(1) in MONTHS:
        return "%s-%02d" % (m.group(2), MONTHS[m.group(1)])
    m = re.match(r"(\d{4})", s)
    return "%s-01" % m.group(1) if m else None


def main(collects_dir, fund_name):
    skip = re.compile(re.escape(fund_name), re.I)
    windows = []
    for path in sorted(glob.glob(os.path.join(collects_dir, "op-*.json"))):
        d = json.load(open(path))
        advisor = re.sub(r"^op-|\.json$", "", os.path.basename(path))
        name = d.get("full_name") or d.get("name") or advisor
        seen = set()
        for e in d.get("experience") or []:
            title = str(e.get("position_title") or e.get("title") or "")
            company = str(e.get("company_name") or "").strip()
            if not company or not BOARD.search(title):
                continue
            if skip.search(company):
                continue
            key = company.lower()
            if key in seen:            # multi-source profiles repeat entries
                continue
            seen.add(key)
            windows.append({
                "advisor": advisor,
                "advisor_name": name,
                "company": company,
                "company_id": e.get("company_id"),
                "title": title,
                "from": norm_date(e.get("date_from")),
                "to": norm_date(e.get("date_to")),   # null = current seat
            })
    json.dump({"windows": windows, "count": len(windows)},
              sys.stdout, indent=2)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
