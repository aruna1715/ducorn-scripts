-- 007_status_truth.sql
--
-- One constraint per table, matching what the code writes.
--
-- approval_requests: /pipeline/stop writes 'cancelled' and the
-- constraint refused it, so killing a run that was parked at a
-- gate rolled back the whole transaction and the run was not even
-- marked stopped. The same defect as gate 2, five days later.
--
-- pipeline_runs, pipeline_skill_runs: no constraint at all, so a
-- typo produced a run that matched no dashboard filter. Values
-- surveyed from the live tables before this was written.

ALTER TABLE approval_requests
    DROP CONSTRAINT IF EXISTS approval_requests_status_check,
    ADD CONSTRAINT approval_requests_status_check
    CHECK (status IN ('pending', 'approved', 'rejected', 'superseded', 'cancelled'));

ALTER TABLE pipeline_runs
    DROP CONSTRAINT IF EXISTS pipeline_runs_status_check,
    ADD CONSTRAINT pipeline_runs_status_check
    CHECK (status IN ('created', 'started', 'running', 'awaiting_approval', 'needs_intervention', 'stopped', 'complete', 'failed', 'archived', 'cancelled'));

ALTER TABLE pipeline_skill_runs
    DROP CONSTRAINT IF EXISTS pipeline_skill_runs_status_check,
    ADD CONSTRAINT pipeline_skill_runs_status_check
    CHECK (status IN ('waiting', 'running', 'complete', 'failed', 'skipped'));
