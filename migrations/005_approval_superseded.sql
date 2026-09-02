-- 005: 'superseded' is a status an approval can actually have.
--
-- Gate 2 raises one approval per design variant, so approving one IS choosing
-- it. The other two are then marked superseded and their id recorded in
-- superseded_by. Migration 002 added that column and the code that writes to
-- it, and never touched the constraint on the column it writes:
--
--     CONSTRAINT approval_requests_status_check
--       CHECK (status IN ('pending', 'approved', 'rejected'))
--
-- So the first real approval of a design failed on the second row:
--
--     new row for relation "approval_requests" violates check constraint
--     "approval_requests_status_check"
--     ... Failing row contains (371, atlas, UI design — approve to build:
--         ducorn-spend-status, ..., superseded, ..., build,
--         ducorn-spend-status, 373)
--
-- Half of a pair, again: the column, the writer and the message were all
-- correct, and the one thing that could refuse them was never asked.
--
-- Widening rather than dropping: an unconstrained status column would let a
-- typo through silently, which is the failure this constraint exists to stop.

ALTER TABLE approval_requests
    DROP CONSTRAINT IF EXISTS approval_requests_status_check;

ALTER TABLE approval_requests
    ADD CONSTRAINT approval_requests_status_check
    CHECK (status IN ('pending', 'approved', 'rejected', 'superseded'));
