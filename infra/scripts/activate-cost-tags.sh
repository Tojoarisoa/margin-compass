#!/usr/bin/env bash
# Activates the five mandatory tags as cost allocation tags (runbook step 6).
# Run it after the tags appear in Billing (can take up to 24 hours after the first deploy).
source "$(dirname "$0")/_common.sh"
require_session
aws ce update-cost-allocation-tags-status --cost-allocation-tags-status \
  TagKey=project,Status=Active TagKey=env,Status=Active TagKey=stage,Status=Active \
  TagKey=owner,Status=Active TagKey=cost-center,Status=Active
ok "Requested activation. Check: https://console.aws.amazon.com/billing/home#/tags"
