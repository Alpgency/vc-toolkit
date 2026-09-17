-- Partner-network engine: graph store.
-- One schema in any Postgres. Plain SQL on purpose: 1-hop path finding over
-- tens of thousands of edges needs no graph database.

CREATE SCHEMA IF NOT EXISTS network;

-- The bench: the fund's partners and advisers. Source of truth for who we
-- map. Never a login, never an account.
CREATE TABLE IF NOT EXISTS network.advisors (
  id           text PRIMARY KEY,          -- linkedin shorthand
  name         text NOT NULL,
  title        text,
  linkedin_url text,
  added_at     timestamptz NOT NULL DEFAULT now(),
  active       boolean NOT NULL DEFAULT true
);

-- Everyone the advisors can reach. One row per person, deduped across
-- advisors by provider id. Negative ids are company anchors for board seats.
CREATE TABLE IF NOT EXISTS network.people (
  id               bigint PRIMARY KEY,    -- provider person id
  name             text NOT NULL,
  current_title    text,
  current_company  text,
  location         text,
  collected_at     timestamptz,           -- null = enumerated only, not enriched
  raw              jsonb                  -- full provider payload when collected
);

CREATE TABLE IF NOT EXISTS network.companies (
  id       bigint PRIMARY KEY,            -- provider company id, or a name hash
  name     text NOT NULL,
  size     integer,
  aliases  text[] NOT NULL DEFAULT '{}'
);

-- The graph. type says where the edge came from; weight is deterministic
-- (the 35/20/15/15/15 model computed by the pipeline, never by an LLM).
CREATE TABLE IF NOT EXISTS network.edges (
  id           bigserial PRIMARY KEY,
  advisor_id   text   NOT NULL REFERENCES network.advisors(id),
  person_id    bigint NOT NULL REFERENCES network.people(id),
  type         text   NOT NULL CHECK (type IN
                 ('confirmed',        -- fund told us, or a connections export row
                  'work_overlap',     -- same employer, verified both sides
                  'board_overlap')),  -- board or advisory seat
  direction    text   NOT NULL DEFAULT 'mutual',
  company_id   bigint REFERENCES network.companies(id),
  occurred_at  daterange,              -- the overlap window
  overlap_years numeric(5,2),
  evidence_url text,
  evidence     text,                   -- one human-readable line, cited
  weight       numeric(4,3) NOT NULL CHECK (weight >= 0 AND weight <= 1),
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (advisor_id, person_id, type, company_id)
);

-- Per-deal sweep results, kept so reports are reproducible and auditable.
CREATE TABLE IF NOT EXISTS network.deal_matches (
  id          bigserial PRIMARY KEY,
  deal_slug   text NOT NULL,
  deal_brief  text NOT NULL,
  target_company text NOT NULL,
  person_id   bigint REFERENCES network.people(id),
  advisor_id  text REFERENCES network.advisors(id),
  path_score  numeric(4,3),
  rationale   text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS edges_person_idx  ON network.edges (person_id);
CREATE INDEX IF NOT EXISTS edges_advisor_idx ON network.edges (advisor_id);
CREATE INDEX IF NOT EXISTS people_company_idx ON network.people (lower(current_company));
