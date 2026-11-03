# Lambda container image for the data pipeline (M1-02). Build context: repository root.
# Dependencies are installed from the committed uv lockfiles before the code is copied, so code
# changes reuse the cached dependency layer.
FROM public.ecr.aws/lambda/python:3.13

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

# 1) Dependencies only (cached unless a lockfile or pyproject changes). One lockfile for the whole
#    image: pipelines/uv.lock already resolves mc-ml's, mc-rag's, and the simulator's runtime dependencies, so
#    nothing can resolve to two different versions.
COPY pipelines/pyproject.toml pipelines/uv.lock /build/pipelines/
COPY simulator/pyproject.toml /build/simulator/
COPY ml/pyproject.toml /build/ml/
COPY rag/pyproject.toml /build/rag/
RUN cd /build/pipelines && uv export --frozen --no-dev --no-emit-project --no-emit-package mc-ml --no-emit-package mc-rag --no-hashes -o /build/requirements.txt \
 && uv pip install --system --no-cache -r /build/requirements.txt

# 2) Code
COPY simulator /build/simulator
COPY ml /build/ml
COPY rag /build/rag
COPY pipelines /build/pipelines
COPY knowledge ${LAMBDA_TASK_ROOT}/knowledge
RUN uv pip install --system --no-cache --no-deps /build/simulator /build/ml /build/rag /build/pipelines \
 && cp -r /build/pipelines/transform ${LAMBDA_TASK_ROOT}/transform \
 && rm -rf /build /usr/local/bin/uv

ENV MC_TRANSFORM_DIR=${LAMBDA_TASK_ROOT}/transform \
    MC_KNOWLEDGE_DIR=${LAMBDA_TASK_ROOT}/knowledge \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    HOME=/tmp

CMD ["mc_pipelines.lambda_handler.handler"]
