#!/usr/bin/env python3
"""Collect every partner profile listed in the config, by LinkedIn shorthand.

Skips profiles already in <work>/collects. Billed: one collect per new partner.

Run: python3 01-collect-partners.py
"""

import json
import os

import coresignal as cs


def main():
    partners = cs.load_config()["partners"]
    os.makedirs(cs.COLLECTS, exist_ok=True)

    print("Collecting partners")
    for p in partners:
        short = p["shorthand"]
        path = os.path.join(cs.COLLECTS, "op-%s.json" % short)
        if os.path.exists(path):
            print("  %s: already collected, skipping" % short)
            continue
        with open(path, "w") as f:
            json.dump(cs.collect(short), f, indent=2)
        print("  %s: collected" % short)

    print("\nPer-partner summary")
    for p in partners:
        with open(os.path.join(cs.COLLECTS, "op-%s.json" % p["shorthand"])) as f:
            exp = cs.experience_entries(json.load(f))
        starts = [s for s in (cs.parse_year(e["date_from"]) for e in exp) if s is not None]
        span = ("%d to now" % min(starts)) if starts else "unknown"
        print("  %-24s entries: %3d  since: %s" % (p["name"], len(exp), span))
        if not exp:
            print("  %-24s WARNING: empty experience list" % "")

    print("\ncredits remaining: %s" % cs.last_known_remaining())
    print("Next: python3 02-derive-targets.py")


if __name__ == "__main__":
    main()
