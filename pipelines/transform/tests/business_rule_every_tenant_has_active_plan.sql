{{ config(severity='error', tags=['business_rule']) }}
-- PLAN.md §6.2 Stage 3: every tenant has an active plan for the whole simulated window. M1 contracts
-- renew automatically at renewal_date (no churn until M3), so active = known plan and started by window start.
select tenant_id, plan, contract_start
from {{ ref('stg_tenants') }}
where plan not in ('starter', 'growth', 'enterprise') or contract_start > date '{{ var("window_start") }}'
