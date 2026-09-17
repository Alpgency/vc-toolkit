#!/usr/bin/env python3
"""Synthetic data generator. Every person and company here is fictional.

Writes fake provider-shaped profiles and search files for the partners in
pipeline/config.example.json into a temp dir, then runs the real
pipeline/05-build-graph.py over them. The scoring and verification that
produce data/network-data.js are the same code a real run uses; only the
inputs are invented. Seeded, so the people are stable between runs (weights
drift slightly with today's date through the recency term).

A few planted facts are asserted by ask/check-graph.mjs:
  - Maren Okafor holds a current board seat at Kestrelway Freight
  - Imogen Thrale overlapped with Tobias Reinholt at Ledgerloom and is now
    the only person currently at Sunmesa Energy
  - Bastian Coldmere overlapped with two partners at two companies

Run: python3 data/generate.py
"""

import json
import os
import random
import subprocess
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(HERE, "..", "pipeline")
CONFIG = os.path.join(PIPELINE, "config.example.json")
OUT = os.path.join(HERE, "network-data.js")

rng = random.Random(42)
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
TODAY = date.today()

FIRST = ["Ada", "Bram", "Marit", "Dorian", "Elsa", "Felix", "Greta", "Hugo",
         "Ines", "Jonas", "Kaia", "Leopold", "Mira", "Nils", "Odette", "Pavel",
         "Rosa", "Soren", "Tilda", "Uma", "Viggo", "Wren", "Yara", "Zeno",
         "Anouk", "Clio", "Emil", "Freya", "Idris", "Linnea"]
LAST = ["Ashdown", "Brackwell", "Coldharbour", "Dunmore", "Everholt", "Fairlight",
        "Glenhart", "Hollowell", "Ivesworth", "Jarrowby", "Kettleby", "Larkspur",
        "Marchbank", "Northcott", "Oakhurst", "Pellingham", "Quarrie", "Rookwood",
        "Stellan", "Thistlewood", "Underhill", "Vantwest", "Winterbourne", "Yewdale"]
TITLES = {
    1: ["Director of Operations", "Director of Finance", "Director of Logistics",
        "Head of Product", "Director of Marketing"],
    2: ["VP Supply Chain", "VP Marketing", "SVP Operations", "VP Engineering",
        "General Manager", "VP Finance"],
    3: ["Chief Operating Officer", "Chief Financial Officer", "Chief Marketing Officer",
        "Chief Technology Officer", "President"],
}
LOCATIONS = ["Example City", "Rivertown", "Lakeport", "Hillview"]


def ym(year, month=1):
    return "%s %d" % (MONTHS[month - 1], year)


def stint(company, title, y_from, y_to, cid, m_from=1, m_to=6):
    return {"company_name": company, "title": title, "company_id": cid,
            "date_from": ym(y_from, m_from),
            "date_to": None if y_to is None else ym(y_to, m_to)}


def main():
    config = json.load(open(CONFIG))
    fund = config["fund"]["name"]
    names = [c["name"] for c in config["companies"]]
    cid = {n: 5000 + i for i, n in enumerate(names + [fund])}
    s = lambda company, title, a, b, **kw: stint(company, title, a, b, cid[company], **kw)

    # partner careers: (company, title, from, to); to=None is current
    partners = {
        "maren-okafor-example": [
            ("Harborline Logistics", "VP Supply Chain", 2008, 2016),
            ("Brightcart Retail", "SVP Logistics", 2016, 2022),
            (fund, "Operating Partner", 2022, None),
            ("Kestrelway Freight", "Board Member", 2023, None),
        ],
        "tobias-reinholt-example": [
            ("Copperfen Bank", "Director of Payments", 2005, 2011),
            ("Ledgerloom", "Chief Financial Officer", 2011, 2021),
            (fund, "Operating Partner", 2022, None),
            ("Orbitquay", "Advisory Board Member", 2024, None),
        ],
        "priya-castellano-example": [
            ("Quillmere Media", "VP Marketing", 2006, 2014),
            ("Pennywhistle Stores", "Chief Marketing Officer", 2014, 2023),
            (fund, "Operating Partner", 2023, None),
        ],
        "dario-venn-example": [
            ("Sunmesa Energy", "Director of Operations", 2004, 2012),
            ("Clearbrook Health", "Chief Operating Officer", 2012, 2020),
            ("Tallpine Software", "President", 2020, 2024),
            (fund, "Venture Partner", 2024, None),
            ("Fernhollow Foods", "Non-Executive Director", 2021, None),
        ],
    }

    tmp = tempfile.TemporaryDirectory(prefix="network-synthetic-")
    work = tmp.name
    collects = os.path.join(work, "collects")
    searches = os.path.join(work, "searches")
    os.makedirs(collects)
    os.makedirs(searches)

    def dump(path, obj):
        with open(path, "w") as f:
            json.dump(obj, f)

    for i, (short, career) in enumerate(partners.items()):
        name = next(p["name"] for p in config["partners"] if p["shorthand"] == short)
        dump(os.path.join(collects, "op-%s.json" % short), {
            "id": 900 + i, "full_name": name, "location_full": rng.choice(LOCATIONS),
            "experience": [s(c, t, a, b) for c, t, a, b in career]})

    people = {}       # id -> profile
    hits = {}         # (partner, company) -> [ids]
    used_names = set()
    next_id = [100001]

    def new_person(name, experience):
        pid = next_id[0]
        next_id[0] += 1
        used_names.add(name)
        people[pid] = {"id": pid, "full_name": name,
                       "location_full": rng.choice(LOCATIONS), "experience": experience}
        return pid

    def fresh_name():
        while True:
            n = "%s %s" % (rng.choice(FIRST), rng.choice(LAST))
            if n not in used_names:
                return n

    # planted people
    imogen = new_person("Imogen Thrale", [
        s("Ledgerloom", "VP Finance", 2013, 2020),
        s("Sunmesa Energy", "Chief Financial Officer", 2020, None, m_from=9)])
    hits.setdefault(("tobias-reinholt-example", "Ledgerloom"), []).append(imogen)
    bastian = new_person("Bastian Coldmere", [
        s("Quillmere Media", "VP Marketing Operations", 2006, 2010),
        s("Copperfen Bank", "VP Marketing", 2010, 2016, m_from=2),
        s("Brightcart Retail", "Chief Marketing Officer", 2016, None, m_from=8)])
    hits.setdefault(("priya-castellano-example", "Quillmere Media"), []).append(bastian)
    hits.setdefault(("tobias-reinholt-example", "Copperfen Bank"), []).append(bastian)

    # random colleagues around every employment window
    elsewhere = [n for n in names if n != "Sunmesa Energy"]
    for short, career in partners.items():
        for company, _title, a, b in career:
            if company == fund or any(k in _title.lower() for k in ("board", "non-executive")):
                continue
            end = b or TODAY.year
            for _ in range(rng.randint(13, 16)):
                band = rng.choice([1, 1, 2, 2, 3])
                title = rng.choice(TITLES[band])
                if rng.random() < 0.1:
                    # decoy: search hit whose own dates never overlap the window
                    start, stop = a - rng.randint(6, 10), a - rng.randint(1, 3)
                else:
                    start = rng.randint(a - 3, end - 1)
                    stop = min(start + rng.randint(2, 9), TODAY.year - 1)
                    stop = max(stop, start + 1)
                exp = [s(company, title, start, stop, m_from=rng.randint(1, 12))]
                if company != "Sunmesa Energy" and rng.random() < 0.25:
                    exp[0]["date_to"] = None  # still there
                else:
                    nxt = rng.choice([n for n in elsewhere if n != company])
                    exp.append(s(nxt, rng.choice(TITLES[min(3, band + 1)]),
                                 stop, None, m_from=rng.randint(7, 12)))
                hits.setdefault((short, company), []).append(new_person(fresh_name(), exp))

    for pid, prof in people.items():
        dump(os.path.join(collects, "person-%d.json" % pid), prof)

    for (short, company), ids in hits.items():
        _c, title, a, b = next(x for x in partners[short] if x[0] == company)
        senior = [i for i in ids if any(k in people[i]["experience"][0]["title"]
                                         for k in ("Chief", "President", "VP", "General Manager"))]
        dump(os.path.join(searches, "%s-%s.json" % (short, company.lower().replace(" ", "-"))), {
            "op": short, "company": company, "op_title": title,
            "window": {"date_from": "%d-01" % a, "date_to": None if b is None else "%d-06" % b},
            "tierA": senior, "tierB": [i for i in ids if i not in senior]})

    env = dict(os.environ, NETWORK_CONFIG=CONFIG, NETWORK_WORK=work, NETWORK_OUT=OUT)
    subprocess.run([sys.executable, os.path.join(PIPELINE, "05-build-graph.py")],
                   env=env, check=True)
    print("synthetic people generated: %d" % len(people))
    tmp.cleanup()


if __name__ == "__main__":
    main()
