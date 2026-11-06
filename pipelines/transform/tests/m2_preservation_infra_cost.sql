{{ config(enabled=var('m2_gates', false) and var('m2_landing_path', '') != '', severity='error', tags=['preservation', 'm2']) }}
-- M2 gate (enabled with var m2_gates, so subset builds in tests do not pick it up): allocated + unallocated shared infrastructure cost equals the FOCUS billed cost, to the cent.
-- Billed is read from the staged export, independent of the allocation model.
with billed as (select sum(effective_cost) as total from {{ ref('stg_m2_focus') }}),
     alloc as (select sum(allocated_cost_usd) as total from {{ ref('fct_infra_cost_allocated') }})
select b.total as billed, a.total as allocated
from billed b, alloc a
where round(b.total, 2) <> round(a.total, 2)
