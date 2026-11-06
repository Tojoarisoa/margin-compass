{{ config(enabled=var('m2_landing_path', '') != '', materialized='view') }}
-- M2 per-ticket outcomes: the 10% sample plus every labeled safety event (so not a uniform sample).
-- No trace ID exists on tickets; they join to telemetry at tenant x day (slv_m2_outcomes_daily).
select
    ticket_id, tenant_id, cast(ticket_date as date) as ticket_date, severity, used_f2, resolved_remotely,
    field_visit_booked, escalated, csat, safety_event_label, safety_flag, eval_score
from read_parquet('{{ var("m2_landing_path") }}/s4_outcomes/month=*/tickets.parquet')
