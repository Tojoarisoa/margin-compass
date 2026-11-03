{{ config(severity='error', tags=['business_rule']) }}
-- PLAN.md §6.2 Stage 3 "every request maps to a tenant and a feature", enforced at the KPI-03 target
-- (owner decision 2026-11-04): individual unattributable rows only warn and are shown as unallocated
-- cost; the run stops when attribution coverage over the window falls below the target.
with window_usage as (
    select u.llm_cost_usd,
           (t.tenant_id is null or u.feature_id is null or u.feature_id not in ('F1')) as is_unallocated
    from {{ ref('fct_llm_usage_daily') }} u
    left join {{ ref('stg_tenants') }} t on t.tenant_id = u.tenant_id
    where u.usage_date between date '{{ var("window_start") }}' and date '{{ var("window_end") }}'
)
select 1 - sum(case when is_unallocated then llm_cost_usd else 0 end) / nullif(sum(llm_cost_usd), 0) as coverage
from window_usage
having 1 - sum(case when is_unallocated then llm_cost_usd else 0 end) / nullif(sum(llm_cost_usd), 0)
       < {{ var('kpi03_min_llm_attribution_coverage') }}
