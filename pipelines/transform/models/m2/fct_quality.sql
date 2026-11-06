{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('gold_path') ~ '/fct_quality.parquet') }}
-- Grain: day x tenant. Outcome sums and quality ratios recomputed from those sums, never averaged
-- (m2-plan.md M2-02). safety_event_recall is NULL on days with no labeled event, so a roll-up must sum
-- safety_events_flagged and safety_events_labeled itself.
select
    outcome_date, tenant_id, tickets, f2_tickets, resolved_remotely, field_visits_booked, escalated,
    safety_events_labeled, safety_events_flagged, safety_flags_total,
    cast(safety_events_flagged * 1.0 / nullif(safety_events_labeled, 0) as decimal(9, 6)) as safety_event_recall,
    cast(resolved_remotely * 1.0 / nullif(f2_tickets, 0) as decimal(9, 6)) as remote_resolution_rate,
    cast(csat_sum * 1.0 / nullif(tickets, 0) as decimal(9, 6)) as csat_avg,
    cast(eval_score_sum / nullif(tickets, 0) as decimal(9, 6)) as eval_score_avg
from {{ ref('stg_m2_outcomes_daily') }}
