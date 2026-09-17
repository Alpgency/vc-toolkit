# Partner network graph

Answers one question for a fund: who on our team can open a door into
company X?

The fund and its partners are known. Everyone around them is inferred from
employment history: two people who held senior roles at the same company at
the same time probably know each other. Each inferred connection gets a
deterministic strength score and is always presented as "likely knows",
never "knows". A partner's current board and advisory seats are the
exception: those are confirmed, present-day doors.

Everything in `data/` is synthetic. "Example Ventures", its partners, the
people and the companies (all on `.example` domains) are invented.

## What is in here

```
web/        static page: force-directed graph, tiers, ask box
ask/        zero-dependency Node server: static files + POST /api/ask
pipeline/   CoreSignal collection and graph build (Python 3 stdlib)
engine/     Postgres schema, scoring views, loader, per-deal sweep report
data/       synthetic generator and its output, network-data.js
```

Requirements: Node 20.6+ (22 tested), Python 3.9+, Postgres 15+ for the
engine only.

## Quick start with the synthetic data

```
python3 data/generate.py        # rebuild data/network-data.js
node ask/check-graph.mjs        # assert the graph tools on known facts
node ask/server.mjs             # http://localhost:8787
```

The graph, tiers and route highlighting work without an API key. The ask
box needs one:

```
cp ask/.env.example ask/.env    # set ANTHROPIC_API_KEY
node --env-file=ask/.env ask/server.mjs
```

Try "Who can get us into Sunmesa Energy?", "Who do we know in logistics?"
or "Who are the partners?".

## How the inference works

1. Collect each partner's full career history.
2. Every employer where a partner spent a year or more becomes a window:
   that company, those dates.
3. Inside each window, search for senior people only. Tier A: VP and above
   whose stint sits inside the window. Tier B: director and up with at
   least a few months of overlap. Oversized result sets are tightened by
   geography, then by function keywords from the partner's own title.
4. Collect the top candidates per partner, deduped across partners (a shared
   colleague costs one collect and yields two edges).
5. Verify every pair from the colleague's own history: same company,
   genuinely overlapping dates. Pairs that fail are dropped.
6. Score what survives. No model is involved:

| Weight | Signal |
|-------:|--------|
| 35% | Overlap length, full marks at 4+ years |
| 20% | Seniority proximity: same band 1.0, one apart 0.6, further 0.2 |
| 15% | Function match: Jaccard overlap of title keywords |
| 15% | Recency: 1.0 within 5 years, fading to 0.2 at 25 |
| 15% | Company size, inverted: under 500 is 1.0, over 10,000 is 0.2 |

0.6 and up is "strong likely", 0.3 to 0.6 is "possible", below 0.3 the edge
is deleted. On the page, a route's strength is the product of its edge
weights, and the highlighted route is the warmest one (Dijkstra over
`1 - weight`), not the shortest.

## Ask the graph

`POST /api/ask` with `{"q": "..."}` returns `{answer, citations}`.

Claude never sees the graph file. It runs a manual tool loop (max 6 rounds)
over four deterministic functions in `ask/graph.mjs`:

- `find_companies(text)`: resolves names or sector words to exact company
  names in the graph
- `doors_to(company)`: ranked doors, people there now first, then by
  strength; a partner's board seat at that company wins outright
- `person_info(person_id)`: one person and every edge with its basis
- `list_partners()`

The system prompt requires every name to come from a tool result, says
"likely knows" for anything inferred, and keeps the overlap company separate
from the current employer (someone met at one company can be today's door
into another). Citations are the `doors_to` rows whose names appear in the
answer. The server has a simple in-memory limit of 10 questions per IP per
minute.

`ask/check-graph.mjs` asserts the tools against planted facts in the
synthetic data. It makes no network calls.

## Running the pipeline on real data

Data source: CoreSignal's employee API (licensed career-history data; no
scraping, no partner logins). Searches are free. Each profile collect costs
credits, so the budget is roughly
`partners + partners x PER_OP_CAP` collects, minus overlap between partners.
Every request is logged with the provider's remaining-credit header, and
billed calls refuse to run below a credit floor.

```
cd pipeline
cp config.example.json config.json   # fund, partners (LinkedIn shorthands), companies
export CORESIGNAL_API_KEY=...

python3 01-collect-partners.py       # billed: one collect per partner
python3 02-derive-targets.py         # free: writes work/targets.json
# review work/targets.json, set "keep": false on windows to skip
python3 03-search-colleagues.py      # free
python3 04-rank-and-collect.py       # billed: asks before spending
NETWORK_OUT=../data/network-data.js python3 05-build-graph.py
```

Config notes: `companies[].size` feeds the size signal when profiles lack an
employee count, `companies[].sector` powers sector words in
`find_companies`, and `geo_terms`/`hq_city` tighten oversized searches.
Collected profiles are personal data: `pipeline/work/` is gitignored, keep
it that way.

## Engine (Postgres)

For a graph that outgrows one static file, or for recurring refreshes:

```
psql < engine/sql/001_schema.sql
psql < engine/sql/002_scoring_views.sql
python3 engine/etl/load_graph.py data/network-data.js | psql
psql -c "select * from network.ranked_paths('sunmesa') limit 8"
python3 engine/report/deal_sweep.py --deal demo \
  --brief "Series A energy analytics" --targets "Sunmesa Energy,Kestrelway Freight"
```

- `network.best_edges`: best edge per partner and person, confirmed first
- `network.current_doors`: who we reach at each company today
- `network.ranked_paths(target)`: doors into a company, current first,
  then by weight
- `network.coverage`: counts for a refresh report
- `deal_sweep.py` writes `out/<deal>.md` and records matches in
  `network.deal_matches`

The loader is idempotent. `engine/etl/derive_board_windows.py` and
`search_board_colleagues.py` extend enumeration to people around a
partner's board seats (search-only, no credits spent).

## Limits

- Co-tenure is a proxy. A large company with overlapping dates can pair two
  people who never met; the size and seniority signals reduce that, they
  do not remove it.
- Coverage depends on how deep you collect. A "no path" answer usually means
  that corner was not collected, not that no door exists.
- Current employer is only as fresh as the last collect.
