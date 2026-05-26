CREATE TABLE IF NOT EXISTS email_notifications (
  id               SERIAL PRIMARY KEY,
  scored_result_id INTEGER      NOT NULL REFERENCES scored_results(id) ON DELETE CASCADE,
  recipient        VARCHAR(255) NOT NULL,
  normalized_url   TEXT         NOT NULL,
  subject          TEXT         NOT NULL,
  sent_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT uq_email_notifications_recipient_url UNIQUE (recipient, normalized_url)
);

CREATE INDEX IF NOT EXISTS ix_email_notifications_scored_result_id
  ON email_notifications(scored_result_id);

CREATE INDEX IF NOT EXISTS ix_email_notifications_recipient
  ON email_notifications(recipient);
