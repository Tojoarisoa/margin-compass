-- fct_llm_usage_daily: one row per day x tenant x feature x model.
select usage_date, tenant_id, feature_id, model_id, count(*) as n
from {{ ref('fct_llm_usage_daily') }}
group by all
having count(*) > 1
