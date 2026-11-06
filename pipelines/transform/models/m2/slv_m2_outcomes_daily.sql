{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('silver_path') ~ '/slv_m2_outcomes_daily.parquet') }}
-- Tenant x day outcomes joined to priced AI usage on the same tenant and day. Outcomes carry no trace ID, so
-- tenant x day is the finest join (m2-plan.md M2-02). Left join from outcomes: a day with tickets but no
-- usage keeps zero requests and cost rather than being dropped.
with usage as (
    select tenant_id, usage_date, sum(request_count) as requests, sum(llm_cost_usd) as llm_cost_usd
    from {{ ref('slv_m2_llm_usage_priced') }}
    group by 1, 2
)
select
    o.*,
    coalesce(u.requests, 0) as requests,
    cast(coalesce(u.llm_cost_usd, 0) as decimal(18, 6)) as llm_cost_usd
from {{ ref('stg_m2_outcomes_daily') }} o
left join usage u on u.tenant_id = o.tenant_id and u.usage_date = o.outcome_date
