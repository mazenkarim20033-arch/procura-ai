-- Integrity triggers. Hand-written; appended to the generated DDL by scripts/gen_ddl.py.

-- 1. audit_log is insert-only (tamper-evident chain lives in the application layer).
create or replace function public.forbid_mutation() returns trigger
language plpgsql set search_path = public as $$
begin
  raise exception using
    message = tg_op || ' on ' || tg_table_name || ' is not allowed (append-only table)',
    errcode = 'restrict_violation';
end $$;

create trigger audit_log_no_update_delete before update or delete on public.audit_log
  for each row execute function public.forbid_mutation();
create trigger audit_log_no_truncate before truncate on public.audit_log
  for each statement execute function public.forbid_mutation();

-- AI assessments and human decisions are never edited after creation.
create trigger assessments_no_update before update on public.assessments
  for each row execute function public.forbid_mutation();
create trigger findings_no_update before update on public.findings
  for each row execute function public.forbid_mutation();
create trigger finding_evidence_no_update before update on public.finding_evidence
  for each row execute function public.forbid_mutation();
create trigger decisions_no_update before update on public.decisions
  for each row execute function public.forbid_mutation();

-- 2. A request can only become approved/rejected through a matching human decision.
create or replace function public.enforce_decision_gate() returns trigger
language plpgsql set search_path = public as $$
declare last_action text;
begin
  if tg_op = 'INSERT' then
    if new.status <> 'submitted' then
      raise exception 'new purchase request must start as submitted'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;

  if new.status is distinct from old.status and new.status in ('approved', 'rejected') then
    select action into last_action from public.decisions
      where request_id = new.id order by created_at desc, id desc limit 1;
    if last_action is distinct from (case new.status when 'approved' then 'approve' else 'reject' end) then
      raise exception using
        message = 'status ' || new.status || ' requires a matching human decision (latest decision: '
                  || coalesce(last_action, 'none') || ')',
        errcode = 'check_violation';
    end if;
  end if;
  return new;
end $$;

create trigger purchase_requests_decision_gate before insert or update of status
  on public.purchase_requests for each row execute function public.enforce_decision_gate();
