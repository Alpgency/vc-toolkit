#!/usr/bin/env python3
"""Seed Twenty from crm/seed-companies.json (fictional companies). Idempotent:
companies/people upsert on domain/email, opportunities dedupe by name.

Run setup_twenty.py first (stages + custom fields must exist).

  TWENTY_BASE_URL=... TWENTY_API_KEY=... python3 crm/seed_twenty.py
"""
import json
import os
import time

from twenty_common import STAGE_BY_TITLE, call, list_records, unwrap

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "seed-companies.json")


def main() -> None:
    with open(DATA) as fh:
        companies = json.load(fh)["companies"]

    existing = {o.get("name") for o in list_records("opportunities", 60)}
    created = skipped = 0
    for c in companies:
        comp = unwrap(
            call(
                "POST",
                "/rest/companies?upsert=true",
                {
                    "name": c["name"],
                    "domainName": {"primaryLinkUrl": "https://" + c["domain"]},
                },
            )
        )
        f = c["founder"]
        person = unwrap(
            call(
                "POST",
                "/rest/people?upsert=true",
                {
                    "name": {"firstName": f["first"], "lastName": f["last"]},
                    # same synthetic first@domain key the intake workflow uses
                    "emails": {"primaryEmail": f"{f['first'].lower()}@{c['domain']}"},
                    "jobTitle": f["title"],
                    "companyId": comp["id"],
                },
            )
        )
        deal_name = f"{c['name']} ({c['round']})"
        if deal_name in existing:
            skipped += 1
        else:
            tags = ",".join(
                t
                for t in (
                    c.get("language", "en"),
                    "stealth" if c.get("stealth") else None,
                    "hot" if c.get("hot") else None,
                )
                if t
            )
            call(
                "POST",
                "/rest/opportunities",
                {
                    "name": deal_name,
                    "stage": STAGE_BY_TITLE[c["stage"]],
                    "score": c.get("score", 0),
                    "tags": tags,
                    "oneLiner": c.get("one_liner", "")[:240],
                    **({"notes": c["notes"]} if c.get("notes") else {}),
                    "companyId": comp["id"],
                    "pointOfContactId": person["id"],
                },
            )
            created += 1
        time.sleep(0.15)
        print(f"  {c['name']}: company={comp['id'][:8]} person={person['id'][:8]}")

    total = len(list_records("opportunities", 60))
    print(f"\nopportunities created={created} skipped={skipped} now_in_crm={total}")
    if total < len(companies):
        raise SystemExit("MISMATCH: fewer opportunities in Twenty than in the seed file")


if __name__ == "__main__":
    main()
