#!/usr/bin/env python3
"""Remove one company (and its people + opportunities) from Twenty, for
re-running a test forward.

  TWENTY_BASE_URL=... TWENTY_API_KEY=... python3 crm/reset_company.py --domain quillory.example

Workflow 02 dedupes on opportunity id (workflow static data), so deleting the
opportunity is enough for the outbound leg to fire again on the next run.
"""
import argparse

from twenty_common import call, list_records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True, help="company domain to remove")
    domain = ap.parse_args().domain.lower()

    target = None
    for rec in list_records("companies", 60):
        url = ((rec.get("domainName") or {}).get("primaryLinkUrl") or "").lower()
        if domain in url:
            target = rec
            break
    if not target:
        raise SystemExit(f"no company with domain {domain}")
    company_id = target["id"]
    company_name = target.get("name", domain)

    deleted_opps = 0
    for rec in list_records("opportunities", 60):
        if rec.get("companyId") == company_id:
            call("DELETE", f"/rest/opportunities/{rec['id']}")
            deleted_opps += 1

    deleted_people = 0
    for rec in list_records("people", 60):
        email = ((rec.get("emails") or {}).get("primaryEmail") or "").lower()
        if rec.get("companyId") == company_id or email.endswith("@" + domain):
            call("DELETE", f"/rest/people/{rec['id']}")
            deleted_people += 1

    call("DELETE", f"/rest/companies/{company_id}")
    print(
        f"removed {company_name}: 1 company, {deleted_people} people, "
        f"{deleted_opps} opportunities"
    )


if __name__ == "__main__":
    main()
