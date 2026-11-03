{{ config(severity='error', tags=['preservation']) }}
-- PLAN.md §6.2 Stage 2 gate: allocated cost-to-serve plus unallocated equals total billed cost, to the cent.
-- Total billed = every priced usage row in silver. Allocated = fct_tenant_margin. Unallocated = usage
-- rows that can't be matched to a known tenant, a known feature, or the simulated window (same rule as
-- agg_exec_kpis.unallocated_llm_cost_usd), computed independently of the margin fact.
with billed as (
    select sum(llm_cost_usd) as total from {{ ref('slv_llm_usage_priced') }}
), allocated as (
    select sum(cost_to_serve_usd) as total from {{ ref('fct_tenant_margin') }}
), unallocated as (
    select coalesce(sum(u.llm_cost_usd), 0) as total
    from {{ ref('fct_llm_usage_daily') }} u
    left join {{ ref('stg_tenants') }} t on t.tenant_id = u.tenant_id
    where t.tenant_id is null or u.feature_id is null or u.feature_id not in ('F1')
       or u.usage_date not between date '{{ var("window_start") }}' and date '{{ var("window_end") }}'
)
select b.total as billed, a.total as allocated, u.total as unallocated
from billed b, allocated a, unallocated u
where round(b.total, 2) != round(a.total + u.total, 2)
