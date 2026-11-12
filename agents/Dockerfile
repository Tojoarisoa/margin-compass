# Lambda container image for the agent API (M1-07). Build context: repository root.
FROM public.ecr.aws/lambda/python:3.13

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

# 1) Dependencies from the committed lockfile (cached unless it changes).
COPY agents/pyproject.toml agents/uv.lock /build/agents/
COPY rag/pyproject.toml /build/rag/pyproject.toml
RUN cd /build/agents && uv export --frozen --no-dev --no-emit-project --no-emit-package mc-rag --no-hashes -o /build/requirements.txt \
 && uv pip install --system --no-cache -r /build/requirements.txt

# 2) Code
#    mc_pipelines is installed without its dependencies: the kpi tool imports only metrics and publish,
#    which need duckdb and pyyaml (both in the agents lockfile), not dbt, ml, or rag.
COPY agents /build/agents
COPY pipelines /build/pipelines
COPY rag /build/rag
COPY metrics ${LAMBDA_TASK_ROOT}/metrics
COPY knowledge ${LAMBDA_TASK_ROOT}/knowledge
RUN uv pip install --system --no-cache --no-deps /build/agents /build/pipelines /build/rag && rm -rf /build /usr/local/bin/uv

ENV MC_METRICS_DIR=${LAMBDA_TASK_ROOT}/metrics \
    MC_KNOWLEDGE_DIR=${LAMBDA_TASK_ROOT}/knowledge \
    HOME=/tmp
CMD ["mc_agents.api.handler"]
