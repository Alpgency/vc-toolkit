-- Deterministic scoring and path views. No model anywhere in here: the LLM
-- jobs (thesis to filters, entity resolution, evidence prose) happen outside
-- the database, and what they produce is stored, not computed at query time.

-- Best edge per advisor-person pair (a pair can hold confirmed + inferred).
CREATE OR REPLACE VIEW network.best_edges AS
SELECT DISTINCT ON (advisor_id, person_id)
  advisor_id, person_id, type, company_id, occurred_at,
  overlap_years, evidence, evidence_url, weight
FROM network.edges
ORDER BY advisor_id, person_id,
  (type = 'confirmed') DESC,  -- confirmed always beats inferred
  weight DESC;

-- Doors into a company: who do we reach that is there NOW.
CREATE OR REPLACE VIEW network.current_doors AS
SELECT p.current_company, p.id AS person_id, p.name, p.current_title,
       e.advisor_id, a.name AS via_advisor, e.type, e.weight, e.evidence
FROM network.people p
JOIN network.best_edges e ON e.person_id = p.id
JOIN network.advisors a   ON a.id = e.advisor_id AND a.active
WHERE p.current_company IS NOT NULL;

-- Ranked paths for a target company (current people first, then strongest).
-- Query with: SELECT * FROM network.ranked_paths('harborline') LIMIT 8;
CREATE OR REPLACE FUNCTION network.ranked_paths(target text)
RETURNS TABLE (person_id bigint, name text, current_title text,
               current_company text, via_advisor text, type text,
               weight numeric, evidence text, is_current boolean) AS $$
  SELECT d.person_id, d.name, d.current_title, d.current_company,
         d.via_advisor, d.type, d.weight, d.evidence,
         lower(d.current_company) LIKE '%' || lower(target) || '%' AS is_current
  FROM network.current_doors d
  WHERE lower(d.current_company) LIKE '%' || lower(target) || '%'
     OR d.person_id IN (
          SELECT e.person_id FROM network.edges e
          JOIN network.companies c ON c.id = e.company_id
          WHERE lower(c.name) LIKE '%' || lower(target) || '%'
             OR EXISTS (SELECT 1 FROM unnest(c.aliases) al
                        WHERE lower(al) LIKE '%' || lower(target) || '%'))
  ORDER BY is_current DESC, d.weight DESC;
$$ LANGUAGE sql STABLE;

-- Coverage stats for the monthly report.
CREATE OR REPLACE VIEW network.coverage AS
SELECT
  (SELECT count(*) FROM network.advisors WHERE active)          AS advisors,
  (SELECT count(*) FROM network.people)                         AS people,
  (SELECT count(*) FROM network.people WHERE collected_at IS NOT NULL) AS enriched,
  (SELECT count(*) FROM network.edges)                          AS edges,
  (SELECT count(*) FROM network.edges WHERE type = 'confirmed') AS confirmed,
  (SELECT count(*) FROM network.edges WHERE type = 'board_overlap') AS board,
  (SELECT count(DISTINCT lower(current_company)) FROM network.people
    WHERE current_company IS NOT NULL)                          AS reachable_companies;
