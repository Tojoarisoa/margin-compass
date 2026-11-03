{{ config(severity='error', tags=['business_rule']) }}
-- PLAN.md §6.2 Stage 3: no negative tokens; cached tokens never exceed input tokens (ADR-015).
select * from {{ ref('slv_llm_usage_priced') }}
where request_count <= 0 or input_tokens < 0 or output_tokens < 0 or cached_input_tokens < 0
   or retry_count < 0 or cached_input_tokens > input_tokens or llm_cost_usd < 0
