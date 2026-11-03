# Lambda container image for the agent API (M1-07). Build context: repository root.
FROM public.ecr.aws/lambda/python:3.13

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

# 1) Dependencies from the committed lockfile (cached unless it changes).
COPY agents/pyproject.toml agents/uv.lock /build/agents/
RUN cd /build/agents && uv export --frozen --no-dev --no-emit-project --no-hashes -o /build/requirements.txt \
 && uv pip install --system --no-cache -r /build/requirements.txt

# 2) Code
COPY agents /build/agents
RUN uv pip install --system --no-cache --no-deps /build/agents && rm -rf /build /usr/local/bin/uv

ENV HOME=/tmp
CMD ["mc_agents.api.handler"]
