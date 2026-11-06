{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('gold_path') ~ '/fct_infra_cost_allocated.parquet') }}
-- Grain: day x tenant x feature x rule. Shared infrastructure cost (FOCUS) allocated by the effective-dated
-- rules in reference/allocation_rules.yml. Exact: cost is split in units of 0.0001 USD with integer weights,
-- and the leftover units go one each to the largest drivers, so allocated + unallocated = billed exactly.
-- Unallocated (rule_id = 'UNALLOCATED', tenant_id/feature_id NULL) is explicit: no matching rule, staging
-- overhead, or a day with no driver activity.
{% set rules = var('allocation_rules')['rules'] %}
with rules as (
{% if rules | length == 0 %}
    select cast(null as varchar) as rule_id, cast(null as date) as effective_from, cast(null as date) as effective_to,
           cast(null as varchar) as service_name, cast(null as varchar) as env, cast(null as varchar) as driver,
           cast(null as varchar) as driver_features where false
{% else %}
{% for r in rules %}
    select '{{ r.rule_id }}' as rule_id, date '{{ r.effective_from }}' as effective_from,
           {% if r.effective_to %}date '{{ r.effective_to }}'{% else %}cast(null as date){% endif %} as effective_to,
           '{{ r.match.service_name }}' as service_name, '{{ r.match.env }}' as env, '{{ r.driver }}' as driver,
           '{{ r.driver_features | join(",") }}' as driver_features
{% if not loop.last %}    union all{% endif %}
{% endfor %}
{% endif %}
),
cost as (
    select charge_date, service_name, coalesce(env_tag, '') as env,
           cast(round(sum(effective_cost) * 10000) as bigint) as units
    from {{ ref('stg_m2_focus') }}
    group by all
),
matched as (
    select c.*, r.rule_id, r.driver, r.driver_features
    from cost c
    left join rules r
      on r.service_name = c.service_name and r.env = c.env
     and c.charge_date >= r.effective_from and (r.effective_to is null or c.charge_date < r.effective_to)
),
weighted as (
    select m.charge_date, m.service_name, m.env, m.units, m.rule_id, d.tenant_id, d.feature_id,
           cast(case m.driver when 'requests' then d.requests when 'tokens' then d.tokens
                              else d.cumulative_input_tokens end as bigint) as w
    from matched m
    join {{ ref('int_m2_alloc_drivers') }} d
      on d.usage_date = m.charge_date
     and (m.driver_features = '*' or list_contains(string_split(m.driver_features, ','), d.feature_id))
    where m.rule_id is not null
),
sized as (
    select *, sum(w) over (partition by charge_date, service_name, env) as w_total
    from weighted where w > 0
),
split as (
    select *, (units * w) // w_total as base_units,
           units - sum((units * w) // w_total) over (partition by charge_date, service_name, env) as leftover,
           row_number() over (partition by charge_date, service_name, env order by w desc, tenant_id, feature_id) as rk
    from sized
),
allocated as (
    select charge_date as cost_date, tenant_id, feature_id, rule_id, service_name,
           base_units + case when rk <= leftover then 1 else 0 end as units
    from split
),
unallocated as (
    select c.charge_date as cost_date, cast(null as varchar) as tenant_id, cast(null as varchar) as feature_id,
           'UNALLOCATED' as rule_id, c.service_name, c.units
    from matched c
    where not exists (select 1 from sized s where s.charge_date = c.charge_date and s.service_name = c.service_name
                                              and s.env = c.env)
)
select cost_date, tenant_id, feature_id, rule_id, service_name,
       cast(sum(units) / 10000.0 as decimal(18, 4)) as allocated_cost_usd
from (select * from allocated union all select * from unallocated)
group by all
