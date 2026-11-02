# Shared helpers for the M0-07 scripts. Sourced, not executed.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-mc-admin}"
export AWS_REGION="us-east-1"
export AWS_DEFAULT_REGION="us-east-1"
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1
CDK_CLI="aws-cdk@2.1147.0"
INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }

version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }

require_tools() {
  command -v aws >/dev/null || fail "AWS CLI not found. Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
  local v; v="$(aws --version 2>&1 | sed -E 's#^aws-cli/([0-9.]+).*#\1#')"
  version_ge "$v" "2.32.0" && ok "AWS CLI $v" || fail "AWS CLI $v is too old; 2.32.0+ is needed for 'aws login'"
  command -v node >/dev/null && ok "Node.js $(node --version)" || fail "Node.js not found. Install: https://nodejs.org/en/download"
  command -v uv >/dev/null && ok "uv $(uv --version | cut -d' ' -f2)" || fail "uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/"
}

require_session() {
  local arn
  arn="$(aws sts get-caller-identity --query Arn --output text 2>/dev/null)" \
    || fail "Not signed in for profile '$AWS_PROFILE'. Run: aws login --profile $AWS_PROFILE"
  ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
  ok "Signed in as $arn (account $ACCOUNT_ID, profile $AWS_PROFILE)"
  case "$arn" in *":root") warn "You are signed in as root. Use your IAM admin user instead (runbook step 1.4).";; esac
}

# CDK's Node SDK may not read 'login_session' profiles yet, so hand it short-lived env credentials.
export_session_credentials() {
  eval "$(aws configure export-credentials --profile "$AWS_PROFILE" --format env)"
  unset AWS_PROFILE  # use the exported temporary credentials from here on
}

# Prints the ARN of an existing AWS-services anomaly monitor, or nothing. One Cost Explorer API call.
existing_service_monitor() {
  aws ce get-anomaly-monitors \
    --query "AnomalyMonitors[?MonitorType=='DIMENSIONAL' && MonitorDimension=='SERVICE'].MonitorArn | [0]" \
    --output text 2>/dev/null | grep -v '^None$' || true
}

cdk_bootstrapped() {
  aws cloudformation describe-stacks --stack-name CDKToolkit --query 'Stacks[0].StackStatus' --output text >/dev/null 2>&1
}
