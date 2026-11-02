#!/usr/bin/env bash
# Tests, bootstraps (if needed), and deploys mc-shared-foundation (runbook step 4).
# Usage: ALERT_EMAIL=you@example.com infra/scripts/deploy-foundation.sh
source "$(dirname "$0")/_common.sh"
: "${ALERT_EMAIL:?Set ALERT_EMAIL, e.g. ALERT_EMAIL=you@example.com $0}"

echo "1. Checks"
require_tools
require_session

echo "2. Tests (synth-time; must pass before anything is deployed)"
cd "$INFRA_DIR"
uv sync -q
uv run pytest -q

echo "3. Existing anomaly monitor"
monitor="$(existing_service_monitor)"
context=(-c "mc:alertEmail=$ALERT_EMAIL")
if [ -n "$monitor" ]; then
  context+=(-c "mc:existingAnomalyMonitorArn=$monitor")
  ok "Reusing $monitor"
else
  ok "None; the stack creates one"
fi

account="$ACCOUNT_ID"
export_session_credentials

echo "4. CDK bootstrap"
if cdk_bootstrapped; then
  ok "Already bootstrapped"
else
  npx -y "$CDK_CLI" bootstrap "aws://$account/us-east-1"
fi

echo "5. Deploy (CDK shows IAM changes and asks you to confirm)"
npx -y "$CDK_CLI" deploy mc-shared-foundation "${context[@]}"

echo
ok "Deployed. Now confirm the SNS e-mail AWS just sent to $ALERT_EMAIL (runbook step 5)."
