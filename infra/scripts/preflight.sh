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

echo "5. Lambda concurrency (new accounts start below the 1,000 default; AWS raises it with usage)"
applied="$(aws service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 --query 'Quota.Value' --output text 2>/dev/null || echo "?")"
default="$(aws service-quotas get-aws-default-service-quota --service-code lambda --quota-code L-B99A9384 --query 'Quota.Value' --output text 2>/dev/null || echo "?")"
if [ "$applied" = "$default" ]; then
  ok "Concurrent executions: ${applied%.0} (the AWS default)"
else
  warn "Concurrent executions: ${applied%.0} (AWS default ${default%.0}). Enough for M1; request an increase before a public demo (runbook D2)"
fi

echo
echo "Preflight finished. Next: ALERT_EMAIL=you@example.com infra/scripts/deploy-foundation.sh"
