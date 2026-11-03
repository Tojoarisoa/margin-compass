#!/usr/bin/env bash
# Build the dashboard and upload it to the lake's site/ prefix, then invalidate CloudFront (M1-07).
# Needs: AWS credentials (e.g. `aws login --profile mc-admin`), node + npm. Usage: infra/scripts/deploy-dashboard.sh [env]
set -euo pipefail
ENV_NAME="${1:-dev}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PROFILE_ARGS=()
[[ -n "${AWS_PROFILE:-}" ]] && PROFILE_ARGS=(--profile "$AWS_PROFILE")

out() { aws cloudformation describe-stacks "${PROFILE_ARGS[@]}" --stack-name "$1" --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text; }
BUCKET="$(out "mc-${ENV_NAME}-data" LakeBucket)"
DIST_ID="$(out "mc-${ENV_NAME}-web" DistributionId)"
URL="$(out "mc-${ENV_NAME}-web" Url)"
[[ -n "$BUCKET" && -n "$DIST_ID" ]] || { echo "stack outputs not found: deploy mc-${ENV_NAME}-data and mc-${ENV_NAME}-web first" >&2; exit 1; }

cd "$REPO/dashboard"
npm ci --no-fund
npm audit --audit-level=moderate
npm run build

# Hashed assets can be cached long; index.html must revalidate.
aws s3 sync "${PROFILE_ARGS[@]}" dist/ "s3://$BUCKET/site/" --delete --exclude "publish/*" --exclude index.html \
  --cache-control "public, max-age=31536000, immutable"
aws s3 cp "${PROFILE_ARGS[@]}" dist/index.html "s3://$BUCKET/site/index.html" --cache-control "no-cache"
aws cloudfront create-invalidation "${PROFILE_ARGS[@]}" --distribution-id "$DIST_ID" --paths /index.html --query Invalidation.Id --output text
echo "Dashboard deployed: $URL"
