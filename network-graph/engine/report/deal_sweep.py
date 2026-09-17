#!/usr/bin/env python3
"""Per-deal sweep: deal brief in, ranked-paths report out.

Deterministic: each target maps to network.ranked_paths() and the ranking is
whatever the SQL says. No model is involved.

Usage:
  python3 engine/report/deal_sweep.py --deal logistics-saas \
      --brief "Series A route-planning SaaS, needs carrier and shipper doors" \
      --targets "Harborline Logistics,Kestrelway Freight" [--top 8]

Writes out/<deal>.md and records rows in network.deal_matches.
PSQL_CMD sets how psql is reached (default: psql, using the standard PG*
environment variables), e.g. PSQL_CMD="docker exec -i my-db psql -U postgres".
"""

import argparse
import csv
import io
import os
import subprocess

PSQL = os.environ.get("PSQL_CMD", "psql")


def q(s):
    return str(s).replace("'", "''")


def psql(sql, csv_out=True):
    cmd = PSQL.split() + (["--csv"] if csv_out else []) + ["-v", "ON_ERROR_STOP=1"]
    r = subprocess.run(cmd, input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("psql failed: " + r.stderr.strip())
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deal", required=True)
    ap.add_argument("--brief", required=True)
    ap.add_argument("--targets", required=True,
                    help="comma-separated target companies")
    ap.add_argument("--top", type=int, default=8)
    args = ap.parse_args()

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    lines = ["# Deal sweep: %s" % args.deal, "", "> %s" % args.brief, ""]
    inserts = []

    for target in targets:
        rows = list(csv.DictReader(io.StringIO(psql(
            "SELECT * FROM network.ranked_paths('%s') LIMIT %d;"
            % (q(target), args.top)))))
        lines.append("## %s" % target)
        if not rows:
            lines.append("No path in the current graph. That is the honest "
                         "answer, not a search failure: every candidate the "
                         "searches surfaced was ranked, and none touches "
                         "this company.")
            lines.append("")
            continue
        for r in rows:
            now = " (there now)" if r["is_current"] == "t" else ""
            lines.append("- **%s**%s, %s at %s. Via %s, %s. Strength %s."
                         % (r["name"], now, r["current_title"] or "?",
                            r["current_company"] or "?", r["via_advisor"],
                            r["evidence"] or r["type"], r["weight"]))
            inserts.append(
                "INSERT INTO network.deal_matches (deal_slug, deal_brief, "
                "target_company, person_id, path_score, rationale) VALUES "
                "('%s', '%s', '%s', %s, %s, '%s');"
                % (q(args.deal), q(args.brief), q(target), r["person_id"],
                   r["weight"], q(r["evidence"] or r["type"])))
        lines.append("")

    if inserts:
        psql("BEGIN;\n" + "\n".join(inserts) + "\nCOMMIT;", csv_out=False)

    os.makedirs("out", exist_ok=True)
    path = os.path.join("out", "%s.md" % args.deal)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print("wrote %s (%d matches recorded)" % (path, len(inserts)))


if __name__ == "__main__":
    main()
