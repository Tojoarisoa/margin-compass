#!/usr/bin/env bash
# Regenerate every architecture diagram PNG in this folder.
# Requires Graphviz (`brew install graphviz`) and uv. The diagrams library is pinned here.
set -euo pipefail
cd "$(dirname "$0")"
for script in overview pipeline edge telemetry retrieval dashboard agent_state; do
  uv run -q --python 3.13 --with diagrams==0.25.1 python "${script}.py"
done
