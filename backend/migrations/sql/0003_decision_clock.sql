-- Decisions are ordered by created_at inside the approval-gate trigger. now() is the transaction start time,
-- so two decisions recorded in one transaction would tie; clock_timestamp() is the actual insertion time.
alter table public.decisions alter column created_at set default clock_timestamp();
