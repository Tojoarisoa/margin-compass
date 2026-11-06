{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('gold_path') ~ '/fct_cost_to_serve.parquet') }}
-- Grain: day x tenant x feature. Fully loaded cost to serve by component: LLM (priced telemetry) plus allocated
-- shared infrastructure by service. Unallocated infrastructure is not here; it stays visible in
-- fct_infra_cost_allocated (rule_id = 'UNALLOCATED'). Full outer join so a day with infra but no LLM cost
-- (or the reverse) keeps its row.
with llm as (
    select usage_date as cost_date, tenant_id, feature_id,
           sum(llm_cost_usd) as llm_cost_usd, sum(request_count) as requests
    from {{ ref('slv_m2_llm_usage_priced') }}
    group by all
),
infra as (
    select cost_date, tenant_id, feature_id,
           sum(allocated_cost_usd) as infra_cost_usd,
           sum(allocated_cost_usd) filter (where service_name = 'Agent Compute') as agent_compute_usd,
           sum(allocated_cost_usd) filter (where service_name in ('Vector Storage', 'Vector Queries')) as vector_usd,
           sum(allocated_cost_usd) filter (where service_name in ('Egress', 'Observability')) as network_observability_usd,
           sum(allocated_cost_usd) filter (where service_name = 'Third-Party APIs') as third_party_usd
    from {{ ref('fct_infra_cost_allocated') }}
    where rule_id <> 'UNALLOCATED'
    group by all
)
select
    coalesce(l.cost_date, i.cost_date) as cost_date,
    coalesce(l.tenant_id, i.tenant_id) as tenant_id,
    coalesce(l.feature_id, i.feature_id) as feature_id,
    coalesce(l.requests, 0) as requests,
    cast(coalesce(l.llm_cost_usd, 0) as decimal(18, 6)) as llm_cost_usd,
    cast(coalesce(i.agent_compute_usd, 0) as decimal(18, 4)) as agent_compute_usd,
    cast(coalesce(i.vector_usd, 0) as decimal(18, 4)) as vector_usd,
    cast(coalesce(i.network_observability_usd, 0) as decimal(18, 4)) as network_observability_usd,
    cast(coalesce(i.third_party_usd, 0) as decimal(18, 4)) as third_party_usd,
    cast(coalesce(i.infra_cost_usd, 0) as decimal(18, 4)) as infra_cost_usd,
    cast(coalesce(l.llm_cost_usd, 0) + coalesce(i.infra_cost_usd, 0) as decimal(18, 6)) as cost_to_serve_usd
from llm l
full outer join infra i
  on i.cost_date = l.cost_date and i.tenant_id = l.tenant_id and i.feature_id = l.feature_id
