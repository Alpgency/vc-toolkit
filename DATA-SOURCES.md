# Data sources and external tools

Every outside service both systems touch, what it is used for, what it costs,
and the options we looked at and did not use. Prices are approximate vendor
list prices checked in September 2026. Verify them before you budget.

Status labels:

- **In code**: the code in this repo calls it.
- **Designed**: part of the design, not built here.
- **Rejected**: evaluated and not used, with the reason.

## Network graph

### Layer 1: CoreSignal employee data (in code)

Licensed career-history data (employee records with company, title and
dates). The pipeline reads each partner's work history, derives the windows
where they worked somewhere, then searches for people whose experience at the
same company overlaps those dates. Overlap length and seniority drive the edge
score.

- API: CoreSignal Employee API, Elasticsearch-style search plus collect by
  profile shorthand.
- Cost model: searches are free. Collecting one full profile costs credits
  (about 10 per profile on the plan we used).
- Scale we measured: four partners produced about 2,400 candidate colleagues.
  A demo depth of ~160 profiles used ~1,600 credits.
- Rough budgets: ~2,500 profiles is about 25,000 credits, one month of a
  mid-tier plan (around USD 500). A full map of ~13,500 profiles is about
  135,000 credits (around USD 1,000 for one month on a larger tier). Ongoing
  refresh fits in 2,000 to 10,000 credits a month (around USD 50 to 200).
- Gotchas we hit: the search endpoint rejects a top-level `size`; date fields
  only parse `YYYY` or `Month YYYY`; use a nested query so company and dates
  match the same experience entry, or you get false overlaps; merge company
  name variants by company id.
- Limits: this is inference. "Worked at the same company at the same time"
  means "likely knows", never "knows". Large employers produce many weak
  edges, which is why the score weights overlap length and team size.

### Board and advisory seats (in code)

Current board and advisory roles come from the same CoreSignal partner
profiles. They are treated as confirmed doors into those companies, with a
higher weight than inferred edges. No extra credits.

### Layer 2: each partner's LinkedIn connections export (designed)

The strongest real signal, and free. Each partner downloads their own
connections file from LinkedIn:

1. LinkedIn, Settings, Data privacy, "Get a copy of your data".
2. Select "Connections" only. The file usually arrives within minutes.
3. `Connections.csv` has first name, last name, profile URL, company,
   position, connected-on date, and email when the contact allows it.

These are real first-degree edges with a date, so they sit on top of the
inferred layer: an inferred edge confirmed by a connection gets promoted, and
connections with no career overlap get added as their own edges. The partner
exports their own data, so there are no shared passwords, no automation
against LinkedIn, and no terms-of-service exposure. The ingest step is not in
this repo; it is a CSV load keyed on the profile URL.

### Layer 3: Sales Navigator, by hand (designed)

For a partner who will not export, a colleague with a Sales Navigator seat can
browse that partner's network in the product and flag the people who matter.
Sales Navigator has no public API for this, so nothing is automated. It is a
person using the product.

### Freshness (designed)

Three speeds keep the data current without bulk re-crawls:

- On query: anyone an answer surfaces gets re-collected if their record is
  older than 30 days.
- Monthly: a watchlist diff on pinned people catches job changes, new board
  seats and arrivals at target companies.
- Quarterly: a re-scan finds new colleagues and covers new partners.

### Engagement signals (designed, not recommended by default)

Who likes or comments on whose LinkedIn posts could feed the strength score.
Getting it at scale means scraping, so add it only as a clearly disclosed
source if you decide the signal is worth that.

### Ask the graph: Claude (in code)

Anthropic Messages API with a manual tool loop over four deterministic graph
tools. The model only interprets the question; ranking comes from the scored
graph and every name in an answer must cite a tool result. Cost is a few cents
per question at typical sizes.

### Engine: Postgres (in code)

Postgres 15 or newer. Schema, scoring views, `ranked_paths()` and the deal
sweep report live in `network-graph/engine`.

### Rejected for the graph

- **LinkedIn scraping actors (Apify and similar) and session-cookie tools.**
  They log in as a real account or scrape profiles, which breaks LinkedIn's
  terms and puts the partner's account at risk.
- **Unipile for connection lists.** Same session-based model, same account
  risk, for data the partner can export for free.
- **LinkedIn's official APIs.** Connection data is not available to
  third-party apps.
- **Buying connection lists.** No legitimate vendor sells another person's
  first-degree connections.

## Deal-flow agent

### Research: Claude with server-side web search (in code)

One Claude call per deal with Anthropic's built-in web search tool
(`web_search_20260209`, up to 8 searches per deal). The model refines its own
queries mid-reasoning, citations come attached to claims, and it can refute a
false claim in the forward. The index behind the tool is Brave Search.

- Cost: USD 10 per 1,000 searches plus tokens. We measured roughly USD 0.20
  per deal on an earlier, shorter prompt; expect more with the full thesis.
- Time: 40 to 60 seconds per company.
- The board is scored 0 to 10 per variable by the model; the weighted total is
  computed in code, so the model cannot move the final number.

### Research options we compared

| Option | What it is | Why not used |
| --- | --- | --- |
| Tavily | Search API for agent loops | Cheaper per search, but you build the loop yourself; ranked below Brave in the one third-party agentic search benchmark we found |
| Perplexity Sonar | One-call answer engine | Reports of fabricated citations; fact-checking is the job here |
| OpenAI or Gemini native search | Same server-side pattern | Lateral move, no evidence either does better |
| Firecrawl | Scrape and crawl | Wrong layer: extraction, not discovery |
| Serper, SerpAPI, Brave API, You.com | Raw search results | You rebuild the agent loop the native tool gives you |
| Exa | Semantic search | Not used yet. The first thing to add if stealth companies get misidentified, since it finds entities by description. About USD 7 per 1,000 searches |
| LinkUp | Grounded search, strong on factual QA | Candidate for a second-source cross-check if you want two-source verification |

### CRM: Twenty (in code)

Open-source CRM, self-hosted with Docker. REST and GraphQL APIs with native
upsert, so re-forwarding a company updates it instead of duplicating it. Cost
is your server. The agent writes companies, people and opportunities with
score, tags, one-liner and notes.

CRMs we compared:

| CRM | API access | Notes |
| --- | --- | --- |
| Twenty | Every install | Self-hosted, AGPL (internal use is fine), no vendor support |
| Attio | Every plan, including free | Cleanest hosted option; free tier covers a small team |
| Affinity | Higher tiers only | Monthly API call cap and a small webhook limit; check your plan before building on it |

### Orchestration: n8n (in code)

Self-hosted n8n runs every workflow and holds every credential. The model
never sees a key. Note that n8n finishes all items in one node before the next
node starts, so in bulk intake every deal lands in the CRM together at the
end.

### Chat interface: Telegram bot (in code)

Forwards come in and confirm cards go out through a Telegram bot (BotFather,
free). The intake only accepts messages from your configured chat id. WhatsApp
works too through the WhatsApp Business API, but it charges per message.

### Outreach: Unipile (in code, optional)

Unipile sends LinkedIn messages and runs people search when a founder's
profile is missing. Roughly EUR 50 a month. It works through a connected
LinkedIn account, so the account risk sits with whoever connects it. Outreach
only fires after a human approves the card. Research does not use Unipile.

### Booking: Cal.com (in code)

A `BOOKING_CREATED` webhook moves the deal to First meeting. If your team
books through Google Calendar appointment schedules instead, swap the trigger
for a calendar watch.

### Alerts: SMTP email (in code)

The error-handler workflow emails failures through any SMTP account.
