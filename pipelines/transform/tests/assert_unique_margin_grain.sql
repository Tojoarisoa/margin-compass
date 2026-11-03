-- fct_tenant_margin: one row per day x tenant x feature.
select margin_date, tenant_id, feature_id, count(*) as n
from {{ ref('fct_tenant_margin') }}
group by all
having count(*) > 1
