{{ config(severity='error', tags=['contract']) }}
-- fct_tenant_margin: exactly one row per day x tenant x feature over the whole simulated window.
with expected as (
    select (select count(*) from {{ ref('stg_tenants') }})
         * (datediff('day', date '{{ var("window_start") }}', date '{{ var("window_end") }}') + 1) as n
), actual as (
    select count(*) as n, count(distinct (margin_date, tenant_id, feature_id)) as n_distinct from {{ ref('fct_tenant_margin') }}
)
select * from actual, expected where actual.n != expected.n or actual.n_distinct != actual.n
