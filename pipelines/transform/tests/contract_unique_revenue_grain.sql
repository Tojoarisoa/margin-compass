{{ config(severity='error', tags=['contract']) }}
-- fct_revenue_daily: one row per day x tenant x revenue component.
select revenue_date, tenant_id, revenue_component, count(*) as n
from {{ ref('fct_revenue_daily') }} group by all having count(*) > 1
