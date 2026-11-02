#!/usr/bin/env bash
# Read-only checks before deploying the foundation stack (runbook step 3). Changes nothing.
# Usage: infra/scripts/preflight.sh            (profile defaults to mc-admin)
source "$(dirname "$0")/_common.sh"

echo "1. Tools"
require_tools

echo "2. Sign-in"
require_session
if grep -q "^\[$AWS_PROFILE\]" ~/.aws/credentials 2>/dev/null; then
  warn "~/.aws/credentials has a [$AWS_PROFILE] section; static keys there override 'aws login'. Remove it."
else
  ok "No static access keys for this profile"
fi

echo "3. Cost Anomaly Detection (one Cost Explorer API call; at most \$0.01)"
monitor="$(existing_service_monitor)"
if [ -n "$monitor" ]; then
  ok "Existing AWS-services monitor found; deploy will reuse it:"
  echo "     $monitor"
else
  ok "No AWS-services monitor yet; the stack will create one"
fi

echo "4. CDK bootstrap"
cdk_bootstrapped && ok "CDKToolkit stack present" || warn "Not bootstrapped yet; deploy-foundation.sh will do it"

echo "5. Lambda quotas (new accounts start lower; the pipeline needs 6,144 MB memory)"
aws service-quotas list-service-quotas --service-code lambda \
  --query "Quotas[?contains(QuotaName,'oncurren') || contains(QuotaName,'emory')].[QuotaName,Value]" \
  --output table 2>/dev/null || warn "Could not read Service Quotas; check them in the console (runbook step 3.2)"

echo
echo "Preflight finished. Next: ALERT_EMAIL=you@example.com infra/scripts/deploy-foundation.sh"
