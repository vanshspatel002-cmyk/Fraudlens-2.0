-- Add a terminal local-review outcome without rewriting historical job payloads.
-- The existing payload/status equality and one-active-job constraints remain.
ALTER TABLE api_jobs DROP CONSTRAINT api_jobs_status_check;
ALTER TABLE api_jobs ADD CONSTRAINT api_jobs_status_check
    CHECK(status IN ('queued','running','completed','completed_partial','failed','interrupted'));
