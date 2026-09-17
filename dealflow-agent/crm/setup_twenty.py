#!/usr/bin/env python3
"""One-time Twenty workspace setup for the dealflow agent. Idempotent.

  TWENTY_BASE_URL=... TWENTY_API_KEY=... python3 crm/setup_twenty.py

Does two things via the metadata API:
1. Replaces the opportunity `stage` select options with the seven pipeline
   stages (NEW, OUT_OF_SCOPE, REACH_OUT, SEQUENCE_RUNNING, REPLIED,
   FIRST_MEETING, SHORTLIST).
2. Creates the custom opportunity fields the workflows write:
   score (NUMBER), tags (TEXT), oneLiner (TEXT), notes (TEXT).

Run this BEFORE seeding and before activating any workflow: the workflows post
these fields and stage values, so Twenty must know them first.
"""
from twenty_common import STAGES, call, unwrap


def main() -> None:
    objects = unwrap(call("GET", "/rest/metadata/objects?limit=200"))
    opp = next(
        (o for o in objects if o.get("nameSingular") == "opportunity"), None
    )
    if not opp:
        raise SystemExit("opportunity object not found in metadata")
    obj_id = opp["id"]
    fields = opp.get("fields") or unwrap(
        call("GET", f"/rest/metadata/objects/{obj_id}")
    ).get("fields", [])
    by_name = {f["name"]: f for f in fields}

    stage = by_name.get("stage")
    if not stage:
        raise SystemExit("stage field not found on opportunity")
    options = [
        {"value": value, "label": label, "color": color, "position": i}
        for i, (value, label, color) in enumerate(STAGES)
    ]
    call("PATCH", f"/rest/metadata/fields/{stage['id']}", {"options": options})
    print(f"stage options set ({len(options)})")

    wanted = [
        ("score", "Score", "NUMBER"),
        ("tags", "Tags", "TEXT"),
        ("oneLiner", "One-liner", "TEXT"),
        ("notes", "Notes", "TEXT"),
    ]
    for name, label, ftype in wanted:
        if name in by_name:
            print(f"field {name}: already exists")
            continue
        call(
            "POST",
            "/rest/metadata/fields",
            {
                "objectMetadataId": obj_id,
                "name": name,
                "label": label,
                "type": ftype,
            },
        )
        print(f"field {name}: created ({ftype})")

    # verify
    objects = unwrap(call("GET", "/rest/metadata/objects?limit=200"))
    opp = next(o for o in objects if o.get("nameSingular") == "opportunity")
    names = {f["name"] for f in opp.get("fields", [])}
    missing = {w[0] for w in wanted} - names
    if missing:
        raise SystemExit(f"MISSING after setup: {missing}")
    stage_f = next(f for f in opp["fields"] if f["name"] == "stage")
    got = {o["value"] for o in (stage_f.get("options") or [])}
    want = {value for value, _, _ in STAGES}
    if got != want:
        raise SystemExit(f"stage options mismatch: {got} != {want}")
    print("verified: stages + custom fields all present")


if __name__ == "__main__":
    main()
