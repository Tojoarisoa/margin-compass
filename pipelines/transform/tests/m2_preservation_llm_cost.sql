{{ config(enabled=var('m2_gates', false) and var('m2_landing_path', '') != '', severity='error', tags=['preservation', 'm2']) }}
-- M2 gate (enabled with var m2_gates, so subset builds in tests do not pick it up): LLM cost in fct_cost_to_serve and fct_unit_cost equals the priced telemetry, to the cent.
with billed as (select sum(llm_cost_usd) as total from {{ ref('slv_m2_llm_usage_priced') }}),
     cts as (select sum(llm_cost_usd) as total from {{ ref('fct_cost_to_serve') }}),
     unit as (select sum(llm_cost_usd) as total from {{ ref('fct_unit_cost') }})
select b.total as billed, c.total as cost_to_serve, u.total as unit_cost
from billed b, cts c, unit u
where round(b.total, 2) <> round(c.total, 2) or round(b.total, 2) <> round(u.total, 2)
