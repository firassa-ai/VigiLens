-- backend/sql/cleanup_belief_duplicates.sql
-- Remove duplicate belief rows before enforcing unique belief keys.

DELETE FROM beliefs b
WHERE b.id NOT IN (
  SELECT DISTINCT ON (drug_id, question_hash, quarter_context) id
  FROM beliefs
  ORDER BY drug_id, question_hash, quarter_context, created_at DESC
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_beliefs_drug_question_quarter
  ON beliefs (drug_id, question_hash, quarter_context);
