{{ config(enabled=var('m2_landing_path', '') != '', materialized='view') }}
-- M2 tenant x day ticket outcomes from the monthly landing chunks (sums, never ratios). Synthetic data.
select
    cast(day as date) as outcome_date, tenant_id, tickets,
    sev1_tickets, sev2_tickets, sev3_tickets, f2_tickets, resolved_remotely, field_visits_booked, escalated,
    csat_sum, safety_events_labeled, safety_events_flagged, safety_flags_total, eval_score_sum
from read_parquet('{{ var("m2_landing_path") }}/s4_outcomes/month=*/daily.parquet')
