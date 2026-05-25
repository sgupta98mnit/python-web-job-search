ALTER TABLE scored_results
  ADD COLUMN IF NOT EXISTS status            VARCHAR(20)  NOT NULL DEFAULT 'discovered',
  ADD COLUMN IF NOT EXISTS notes             TEXT,
  ADD COLUMN IF NOT EXISTS applied_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ  NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS ix_scored_results_status ON scored_results(status);

CREATE TABLE IF NOT EXISTS resume_versions (
  id                 SERIAL PRIMARY KEY,
  scored_result_id   INTEGER       NOT NULL REFERENCES scored_results(id) ON DELETE CASCADE,
  llm_call_id        INTEGER                REFERENCES llm_calls(id)      ON DELETE SET NULL,
  generated_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
  tex_content        TEXT          NOT NULL,
  model              VARCHAR(120)  NOT NULL,
  prompt_hash        VARCHAR(64)   NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_resume_versions_scored_result
  ON resume_versions(scored_result_id);
