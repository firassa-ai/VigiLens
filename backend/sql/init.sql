-- backend/sql/init.sql
-- PostgreSQL 16

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1) drugs
CREATE TABLE IF NOT EXISTS drugs (
  id TEXT PRIMARY KEY, -- e.g., 'semaglutide'
  generic_name TEXT NOT NULL,
  brand_names TEXT[] NOT NULL DEFAULT '{}',
  approved_date DATE NULL,
  description TEXT NOT NULL DEFAULT ''
);

-- 2) faers_reports
-- Stores ONE row per safetyreportid (latest version only).
CREATE TABLE IF NOT EXISTS faers_reports (
  safetyreportid TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  receivedate DATE NOT NULL,
  patient_sex TEXT NOT NULL CHECK (patient_sex IN ('male','female','unknown')),
  patient_age NUMERIC NULL, -- years (float allowed)
  serious BOOLEAN NOT NULL DEFAULT FALSE,
  outcomes TEXT[] NOT NULL DEFAULT '{}',
  raw_json JSONB NOT NULL,
  is_duplicate BOOLEAN NOT NULL DEFAULT FALSE
);

-- 3) faers_report_reactions (junction)
CREATE TABLE IF NOT EXISTS faers_report_reactions (
  safetyreportid TEXT NOT NULL REFERENCES faers_reports(safetyreportid) ON DELETE CASCADE,
  meddra_pt TEXT NOT NULL,
  PRIMARY KEY (safetyreportid, meddra_pt)
);

-- 4) faers_report_drugs (junction)
CREATE TABLE IF NOT EXISTS faers_report_drugs (
  safetyreportid TEXT NOT NULL REFERENCES faers_reports(safetyreportid) ON DELETE CASCADE,
  drug_id TEXT NULL REFERENCES drugs(id) ON DELETE SET NULL,
  drug_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('suspect','concomitant','interacting','unknown')),
  PRIMARY KEY (safetyreportid, drug_name, role)
);

-- 5) quarterly_stats
-- Precomputed per (drug_id, quarter, adverse_event) "as-of" quarter end (cumulative).
CREATE TABLE IF NOT EXISTS quarterly_stats (
  drug_id TEXT NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
  quarter TEXT NOT NULL, -- 'YYYY-QN'
  adverse_event TEXT NOT NULL, -- MedDRA PT

  -- Counts
  report_count INTEGER NOT NULL,       -- a_q: drug+event in THIS quarter
  cumulative_count INTEGER NOT NULL,   -- a: drug+event cumulative through quarter end
  drug_total_cumulative INTEGER NOT NULL, -- a+b: all suspect reports for drug cumulative
  all_total_cumulative INTEGER NOT NULL,  -- a+b+c+d: all FAERS reports cumulative (from openFDA totals)
  all_event_cumulative INTEGER NOT NULL,  -- a+c: all FAERS reports with event cumulative

  -- Disproportionality metrics (cumulative)
  ror DOUBLE PRECISION NULL,
  ror_ci_lower DOUBLE PRECISION NULL,
  ror_ci_upper DOUBLE PRECISION NULL,
  prr DOUBLE PRECISION NULL,
  chi_squared DOUBLE PRECISION NULL,
  bcpnn_ic DOUBLE PRECISION NULL,
  bcpnn_ic025 DOUBLE PRECISION NULL,
  ebgm DOUBLE PRECISION NULL,
  eb05 DOUBLE PRECISION NULL,

  signal_detected BOOLEAN NOT NULL DEFAULT FALSE,
  term_level TEXT NOT NULL DEFAULT 'pt',
  family_key TEXT NULL,
  family_label TEXT NULL,
  method_votes JSONB NOT NULL DEFAULT '{}'::jsonb,
  consensus_tier TEXT NOT NULL DEFAULT 'none',
  label_status TEXT NOT NULL DEFAULT 'unknown',
  priority_flag BOOLEAN NOT NULL DEFAULT FALSE,
  supporting_terms TEXT[] NOT NULL DEFAULT '{}',
  trajectory TEXT NOT NULL CHECK (trajectory IN ('accelerating','emerging','stable','declining','insufficient_data')),

  PRIMARY KEY (drug_id, quarter, adverse_event)
);

-- 5b) faers_background_counts
-- Cached all-FAERS cumulative comparator counts per quarter/event.
-- adverse_event='__ALL__' stores quarter total baseline.
CREATE TABLE IF NOT EXISTS faers_background_counts (
  quarter TEXT NOT NULL,
  adverse_event TEXT NOT NULL,
  all_total_cumulative INTEGER NOT NULL,
  all_event_cumulative INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'openfda',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (quarter, adverse_event)
);

CREATE INDEX IF NOT EXISTS idx_faers_background_quarter ON faers_background_counts(quarter);

-- 6) beliefs
CREATE TABLE IF NOT EXISTS beliefs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  drug_id TEXT NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
  question_hash TEXT NOT NULL,
  question_text TEXT NOT NULL,
  answer_text TEXT NOT NULL,
  confidence_score INTEGER NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 100),
  evidence_report_ids TEXT[] NOT NULL DEFAULT '{}',
  episodic_ids_used TEXT[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  quarter_context TEXT NOT NULL,

  -- Retroactive reinterpretation support
  reinterpreted_report_ids TEXT[] NOT NULL DEFAULT '{}',
  reinterpretation_reason JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_beliefs_drug_created ON beliefs(drug_id, created_at);
CREATE INDEX IF NOT EXISTS idx_beliefs_hash ON beliefs(drug_id, question_hash);
CREATE UNIQUE INDEX IF NOT EXISTS uq_beliefs_drug_question_quarter
  ON beliefs(drug_id, question_hash, quarter_context);

-- 7) fda_actions
CREATE TABLE IF NOT EXISTS fda_actions (
  id TEXT PRIMARY KEY,
  drug_id TEXT NOT NULL,
  date DATE NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('label_change','safety_communication','warning')),
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  source_url TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fda_actions_drug_date ON fda_actions(drug_id, date);

-- 8) predictions
CREATE TABLE IF NOT EXISTS predictions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  drug_id TEXT NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
  adverse_event TEXT NOT NULL,
  predicted_action TEXT NOT NULL CHECK (predicted_action IN ('label_change','safety_communication','warning')),
  confidence INTEGER NOT NULL CHECK (confidence >= 0 AND confidence <= 100),
  predicted_date_start DATE NOT NULL,
  predicted_date_end DATE NOT NULL,
  created_at_quarter TEXT NOT NULL,
  visibility TEXT NOT NULL DEFAULT 'public',
  track TEXT NOT NULL DEFAULT 'receipt' CHECK (track IN ('receipt','proof')),
  novelty_status TEXT NOT NULL DEFAULT 'label_gap'
    CHECK (novelty_status IN ('known_label','label_gap','indication_confounded','generic_noise')),
  evidence_grade TEXT NOT NULL DEFAULT 'moderate',
  trigger_basis TEXT NOT NULL DEFAULT 'signal_threshold',
  label_gap BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_predictions_drug_quarter ON predictions(drug_id, created_at_quarter);

-- 9) ingestion_state
CREATE TABLE IF NOT EXISTS ingestion_state (
  drug_id TEXT PRIMARY KEY REFERENCES drugs(id) ON DELETE CASCADE,
  quarters_loaded TEXT[] NOT NULL DEFAULT '{}',
  next_quarter TEXT NULL,
  evermemos_status TEXT NOT NULL CHECK (evermemos_status IN ('idle','ingesting','consolidating','ready')) DEFAULT 'idle',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 9b) tracking_jobs
CREATE TABLE IF NOT EXISTS tracking_jobs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  status TEXT NOT NULL CHECK (status IN ('queued','running','ready','failed')) DEFAULT 'queued',
  step TEXT NOT NULL CHECK (
    step IN (
      'queued',
      'resolving_identity',
      'fetching_faers',
      'deduping_transforming',
      'seeding_database',
      'computing_baseline_stats',
      'writing_memory',
      'ready',
      'failed'
    )
  ) DEFAULT 'queued',
  progress INTEGER NOT NULL CHECK (progress >= 0 AND progress <= 100) DEFAULT 0,
  medication_name TEXT NOT NULL,
  resolved_generic_name TEXT NULL,
  drug_id TEXT NULL,
  source TEXT NULL,
  error TEXT NULL,
  options_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tracking_jobs_status_updated
  ON tracking_jobs(status, updated_at DESC);

-- 10) situation_analyses
CREATE TABLE IF NOT EXISTS situation_analyses (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  drug_id TEXT NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
  quarter TEXT NOT NULL,
  narrative TEXT NOT NULL,
  risk_level TEXT NOT NULL CHECK (risk_level IN ('low','moderate','elevated','high')),
  key_changes JSONB NOT NULL DEFAULT '[]'::jsonb,
  memory_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
  belief_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (drug_id, quarter)
);

CREATE INDEX IF NOT EXISTS idx_situation_analyses_drug_quarter ON situation_analyses(drug_id, quarter);

-- 11) evermemos_requests
CREATE TABLE IF NOT EXISTS evermemos_requests (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  drug_id TEXT NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
  quarter TEXT NULL,
  endpoint TEXT NOT NULL,
  request_body JSONB NOT NULL,
  response_body JSONB NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','ok','failed')) DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evermemos_requests_drug ON evermemos_requests(drug_id, created_at);

-- 11) evermemos_memory_cache
CREATE TABLE IF NOT EXISTS evermemos_memory_cache (
  memory_id TEXT PRIMARY KEY,
  drug_id TEXT NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
  group_id TEXT NULL,
  memory_type TEXT NULL,
  quarter TEXT NULL,
  source_endpoint TEXT NULL,
  raw_payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evermemos_memory_cache_drug_seen
  ON evermemos_memory_cache(drug_id, last_seen_at DESC);

-- ===== Indexes justified by queries =====
-- Timeline query:
-- SELECT * FROM quarterly_stats WHERE drug_id=$1 AND quarter = ANY($2) ORDER BY quarter, adverse_event;
CREATE INDEX IF NOT EXISTS idx_quarterly_stats_drug_quarter ON quarterly_stats(drug_id, quarter);

-- Active signals query:
-- SELECT * FROM quarterly_stats WHERE drug_id=$1 AND quarter=$2 AND signal_detected=true ORDER BY ror_ci_lower DESC;
CREATE INDEX IF NOT EXISTS idx_quarterly_stats_signal ON quarterly_stats(drug_id, quarter, signal_detected);

-- Evidence query:
-- SELECT * FROM faers_reports WHERE safetyreportid=$1;
-- reactions/drugs are PK-indexed already.

-- ===== Seed data =====

INSERT INTO drugs (id, generic_name, brand_names, approved_date, description)
VALUES
  ('semaglutide', 'semaglutide', ARRAY['Ozempic','Wegovy','Rybelsus'], '2017-12-01',
   'GLP-1 receptor agonist. Demo focuses on FAERS signals over time.'),
  ('minoxidil', 'minoxidil', ARRAY['Rogaine'], '1988-08-18',
   'Topical hair-loss treatment used as the proof-backed generalization demo.'),
  ('metformin', 'metformin', ARRAY['Glucophage'], '1995-01-01',
   'Long-established biguanide used as control.'),
  ('ciprofloxacin', 'ciprofloxacin', ARRAY['Cipro'], '1987-01-01',
   'Optional control drug; not loaded by default.')
ON CONFLICT (id) DO NOTHING;

-- FDA actions (verified sources)
INSERT INTO fda_actions (id, drug_id, date, type, title, description, source_url)
VALUES
  ('ozempic_label_2023_09_ileus', 'semaglutide', '2023-09-01', 'label_change',
   'Ozempic label revised (Sep 2023): Ileus added to postmarketing GI disorders',
   'Postmarketing Experience includes: Gastrointestinal Disorders: Ileus.',
   'https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?audience=consumer&setid=adec4fd2-6858-4c99-91d4-531f5f2a2d79'),
  ('fda_glp1_suicidal_update_2024_01_11', 'semaglutide', '2024-01-11', 'safety_communication',
   'FDA update on ongoing evaluation of reports of suicidal thoughts/actions with GLP-1 receptor agonists',
   'Class-wide FDA update including semaglutide products.',
   'https://www.fda.gov/drugs/drug-safety-and-availability/update-fdas-ongoing-evaluation-reports-suicidal-thoughts-or-actions-patients-taking-certain-type'),
  ('fda_glp1_suicidal_update_2026_01_13', 'semaglutide', '2026-01-13', 'warning',
   'FDA requests removal of suicidal behavior warning from GLP-1 receptor agonists',
   'FDA update and removal request page.',
   'https://www.fda.gov/drugs/drug-safety-and-availability/fda-requests-removal-suicidal-behavior-warning-glp-1-receptor-agonists')
ON CONFLICT (id) DO UPDATE
SET
  drug_id = EXCLUDED.drug_id,
  date = EXCLUDED.date,
  type = EXCLUDED.type,
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  source_url = EXCLUDED.source_url;

-- Ingestion state initial
INSERT INTO ingestion_state (drug_id, quarters_loaded, next_quarter, evermemos_status)
VALUES
  ('semaglutide', ARRAY[]::TEXT[], '2018-Q1', 'idle'),
  ('minoxidil', ARRAY[]::TEXT[], '2018-Q1', 'idle'),
  ('metformin', ARRAY[]::TEXT[], '2018-Q1', 'idle')
ON CONFLICT (drug_id) DO NOTHING;
