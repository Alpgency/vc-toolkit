#!/usr/bin/env python3
"""Turn a network-data.js graph file into idempotent SQL for the network schema.

Emits INSERT ... ON CONFLICT statements to stdout, so loading is one pipe:

  python3 engine/etl/load_graph.py data/network-data.js | psql "$DATABASE_URL"

Loads partners, colleagues, work-overlap edges and the partners' current
board seats (as board_overlap edges to a company anchor row, weight 0.97).
No database driver needed. Weights arrive precomputed by the pipeline; this
loader stores, it never scores.
"""

import hashlib
import json
import re
import sys


def q(s):
    return "NULL" if s is None else "'" + str(s).replace("'", "''") + "'"


def name_hash(name, digits):
    return int(hashlib.md5(name.lower().encode()).hexdigest()[:digits], 16)


def person_id(node_id):
    m = re.match(r"cs-(\d+)$", str(node_id))
    return int(m.group(1)) if m else None


def daterange(window):
    # "2022-01 to 2026-08" -> '[2022-01-01,2026-08-01]'
    m = re.match(r"(\d{4}-\d{2}) to (\d{4}-\d{2})", window or "")
    return "'[%s-01,%s-01]'" % (m.group(1), m.group(2)) if m else "NULL"


def read_graph(path):
    raw = open(path).read()
    if path.endswith(".json"):
        return json.loads(raw)
    start = raw.index("=", raw.index("window.NETWORK_DATA")) + 1
    return json.loads(raw[start:].strip().rstrip(";"))


def main(path):
    data = read_graph(path)
    nodes = {n["id"]: n for n in data["nodes"]}
    out = ["BEGIN;"]

    for n in data["nodes"]:
        if n.get("kind") == "op":
            out.append(
                "INSERT INTO network.advisors (id, name, title, linkedin_url) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET "
                "name = EXCLUDED.name, title = EXCLUDED.title;"
                % (q(n["id"]), q(n["name"]), q(n.get("title")), q(n.get("linkedin") or None)))
        elif n.get("kind") == "colleague" and person_id(n["id"]) is not None:
            out.append(
                "INSERT INTO network.people (id, name, current_title, "
                "current_company, location, collected_at) "
                "VALUES (%d, %s, %s, %s, %s, now()) ON CONFLICT (id) DO UPDATE "
                "SET current_title = EXCLUDED.current_title, "
                "current_company = EXCLUDED.current_company;"
                % (person_id(n["id"]), q(n["name"]), q(n.get("title")),
                   q(n.get("employer")), q(n.get("location"))))

    # the data file carries company names, not provider ids; a stable hash
    # keeps rows addressable until enrichment backfills real ids
    companies = sorted({(e.get("basis") or {}).get("company") for e in data["edges"]} - {None})
    for c in companies:
        out.append("INSERT INTO network.companies (id, name) VALUES (%d, %s) "
                   "ON CONFLICT (id) DO NOTHING;" % (name_hash(c, 12), q(c)))

    for e in data["edges"]:
        src, tgt = nodes.get(e["source"]), nodes.get(e["target"])
        # partner -> colleague edges only; the fund tie is the advisors table
        if not src or not tgt or src.get("kind") != "op" or tgt.get("kind") != "colleague":
            continue
        pid = person_id(tgt["id"])
        if pid is None:
            continue
        basis = e.get("basis") or {}
        comp, years = basis.get("company"), basis.get("overlap_years")
        evidence = "overlapped with %s at %s%s%s" % (
            src["name"], comp or "?",
            " for %s years" % years if years else "",
            " (%s)" % basis["window"] if basis.get("window") else "")
        out.append(
            "INSERT INTO network.edges (advisor_id, person_id, type, company_id, "
            "occurred_at, overlap_years, evidence, weight) "
            "VALUES (%s, %d, 'work_overlap', %s, %s, %s, %s, %s) "
            "ON CONFLICT (advisor_id, person_id, type, company_id) "
            "DO UPDATE SET weight = EXCLUDED.weight, evidence = EXCLUDED.evidence;"
            % (q(src["id"]), pid, str(name_hash(comp, 12)) if comp else "NULL",
               daterange(basis.get("window")),
               "NULL" if years is None else str(years), q(evidence), e.get("weight", 0)))

    for s in data.get("advisorySeats") or []:
        # negative id space keeps company anchors clear of provider person ids
        aid = -name_hash(s["company"], 11)
        since = s.get("since")
        out.append(
            "INSERT INTO network.people (id, name, current_company) VALUES "
            "(%d, %s, %s) ON CONFLICT (id) DO NOTHING;"
            % (aid, q(s["company"] + " (board)"), q(s["company"])))
        evidence = "%s holds a %s seat at %s%s" % (
            s["advisor_name"], s["title"], s["company"], " since %s" % since if since else "")
        out.append(
            "INSERT INTO network.edges (advisor_id, person_id, type, occurred_at, "
            "evidence, weight) VALUES (%s, %d, 'board_overlap', %s, %s, 0.970) "
            "ON CONFLICT (advisor_id, person_id, type, company_id) "
            "DO UPDATE SET evidence = EXCLUDED.evidence;"
            % (q(s["advisor_id"]), aid, "'[%s-01-01,)'" % since if since else "NULL", q(evidence)))

    out.append("COMMIT;")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
