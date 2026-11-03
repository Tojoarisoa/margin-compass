{{ config(severity='error', tags=['preservation']) }}
-- The unallocated amount shown on the dashboard (agg_exec_kpis) equals the unallocated usage rows inside
-- the window, to the cent.
with rows_ as (
    select coalesce(sum(u.llm_cost_usd), 0) as total
    from {{ ref('fct_llm_usage_daily') }} u
    left join {{ ref('stg_tenants') }} t on t.tenant_id = u.tenant_id
    where (t.tenant_id is null or u.feature_id is null or u.feature_id not in ('F1'))
      and u.usage_date between date '{{ var("window_start") }}' and date '{{ var("window_end") }}'
), kpi as (select sum(unallocated_llm_cost_usd) as total from {{ ref('agg_exec_kpis') }})
select * from rows_, kpi where round(rows_.total, 2) != round(kpi.total, 2)
