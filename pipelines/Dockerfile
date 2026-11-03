# Lambda container image for the data pipeline (M1-02). Build context: repository root.
# Dependencies are installed from the committed uv lockfiles before the code is copied, so code
# changes reuse the cached dependency layer.
FROM public.ecr.aws/lambda/python:3.13

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

# 1) Dependencies only (cached unless a lockfile or pyproject changes)
COPY pipelines/pyproject.toml pipelines/uv.lock /build/pipelines/
COPY simulator/pyproject.toml simulator/uv.lock /build/simulator/
RUN cd /build/pipelines && uv export --frozen --no-dev --no-emit-project --no-hashes -o /build/req-pipelines.txt \
 && cd /build/simulator && uv export --frozen --no-dev --no-emit-project --no-hashes -o /build/req-simulator.txt \
 && uv pip install --system --no-cache -r /build/req-pipelines.txt -r /build/req-simulator.txt

# 2) Code
COPY simulator /build/simulator
COPY pipelines /build/pipelines
RUN uv pip install --system --no-cache --no-deps /build/simulator /build/pipelines \
 && cp -r /build/pipelines/transform ${LAMBDA_TASK_ROOT}/transform \
 && rm -rf /build /usr/local/bin/uv

ENV MC_TRANSFORM_DIR=${LAMBDA_TASK_ROOT}/transform \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    HOME=/tmp

CMD ["mc_pipelines.lambda_handler.handler"]
