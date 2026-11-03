{{ config(severity='warn', tags=['statistical']) }}
-- PLAN.md §6.2 Stage 3 statistical check (volume): every day in the window has some LLM usage.
-- Warn, not error: a quiet day is suspicious but not necessarily wrong.
select d::date as day
from generate_series(date '{{ var("window_start") }}', date '{{ var("window_end") }}', interval 1 day) as g(d)
where d::date not in (select usage_date from {{ ref('fct_llm_usage_daily') }})
