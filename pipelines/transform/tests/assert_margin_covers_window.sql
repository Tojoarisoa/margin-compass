-- fct_tenant_margin covers every day of the simulated window for every tenant.
select count(*) as n
from {{ ref('fct_tenant_margin') }}
having count(*) != (select count(*) from {{ ref('stg_tenants') }})
                    * (datediff('day', date '{{ var("window_start") }}', date '{{ var("window_end") }}') + 1)
