#!/usr/bin/env python3
"""Fill each partner's colleague quota and collect the deduped set of profiles.

Quota fill: Tier A ids first, then Tier B, round-robin across the partner's
windows in targets.json order, capped at PER_OP_CAP per partner. Ids are
deduped across ALL partners before collecting: a shared colleague costs one
collect and yields several edges. Billed: one collect per new profile. The
client refuses billed calls below the credit floor, and a 402 aborts the run.

Run: python3 04-rank-and-collect.py
"""

import json
import os
import sys

import coresignal as cs

PER_OP_CAP = 40


def interleave(windows):
    out, idx = [], 0
    while any(windows):
        w = windows[idx % len(windows)]
        if w:
            out.append(w.pop(0))
        idx += 1
    return out


def main():
    if not os.path.exists(cs.TARGETS):
        raise SystemExit("targets.json missing. Run 02 and 03 first.")
    with open(cs.TARGETS) as f:
        data = json.load(f)
    os.makedirs(cs.COLLECTS, exist_ok=True)

    print("Filling per-partner quotas (cap %d, tier A first)" % PER_OP_CAP)
    selected = {}
    for short, entry in data["ops"].items():
        # per-window lists, interleaved so one large window cannot starve
        # the others out of the quota
        windows_a, windows_b = [], []
        for t in entry["targets"]:
            if not t.get("keep"):
                continue
            path = os.path.join(cs.SEARCHES, "%s-%s.json" % (short, cs.slug(t["company"])))
            if not os.path.exists(path):
                print("  %s: no search file for %s, skipping" % (short, t["company"]))
                continue
            with open(path) as f:
                s = json.load(f)
            windows_a.append(list(s.get("tierA", [])))
            windows_b.append(list(s.get("tierB", [])))

        picks, seen = [], set()
        for i in interleave(windows_a) + interleave(windows_b):
            if i in seen:
                continue
            seen.add(i)
            picks.append(i)
            if len(picks) >= PER_OP_CAP:
                break
        selected[short] = picks
        print("  %-28s %d selected" % (short, len(picks)))

    union = list(dict.fromkeys(i for picks in selected.values() for i in picks))
    to_collect = [i for i in union
                  if not os.path.exists(os.path.join(cs.COLLECTS, "person-%d.json" % i))]

    print("\nunion across partners: %d ids" % len(union))
    print("already collected: %d" % (len(union) - len(to_collect)))
    print("to collect now   : %d (about %d credits)"
          % (len(to_collect), len(to_collect) * cs.COLLECT_COST))
    print("credits remaining: %s" % cs.last_known_remaining())

    if not to_collect:
        print("\nNothing to collect. Next: python3 05-build-graph.py")
        return
    if sys.stdin.isatty():
        ans = input("Proceed with %d collects? [y/N] " % len(to_collect))
        if ans.strip().lower() != "y":
            print("Aborted, nothing collected.")
            return

    for n, i in enumerate(to_collect, 1):
        with open(os.path.join(cs.COLLECTS, "person-%d.json" % i), "w") as f:
            json.dump(cs.collect(i), f, indent=2)
        if n % 10 == 0 or n == len(to_collect):
            print("  %d/%d collected, remaining=%s"
                  % (n, len(to_collect), cs.last_known_remaining()))

    print("\nDone. Next: python3 05-build-graph.py")


if __name__ == "__main__":
    main()
