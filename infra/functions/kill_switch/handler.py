"""Kill-switch handler (PLAN.md §11.3 item 4, game-day gap G1): make the app follow the $5 deny policy.

Triggered by every message on the account alert topic (budget, anomaly, alarm) and by ops `kill-switch-sync`.
It never parses the message: it reads the real state (is the kill-switch deny policy attached to the API role?)
and reconciles, so a $3 alert or an anomaly mail does nothing, and running it twice is harmless.

Engaged (policy attached): API reserved concurrency 0, enabled mc-* schedules disabled, public flag
`publish/latest/kill_switch.json` written (the dashboard shows "paused"). What it changed is kept in a private
lake key so lifting restores exactly that. Lifted (policy detached, private state present): concurrency back,
those schedules re-enabled, flag and state removed. No model calls, no deletes outside its two keys.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime

FLAG_KEY = "publish/latest/kill_switch.json"  # public (CloudFront /publish/*): no names, only active/since
STATE_KEY = "kill_switch/state.json"  # private: CloudFront may read only site/* and publish/*
SCHEDULE_FIELDS = ("Name", "GroupName", "ScheduleExpression", "ScheduleExpressionTimezone", "StartDate", "EndDate",
                   "Description", "FlexibleTimeWindow", "Target", "KmsKeyArn", "ActionAfterCompletion")

log = logging.getLogger()
log.setLevel(logging.INFO)


def _emit(run_id: str, event: str, **fields) -> None:
    log.info(json.dumps({"event": event, "run_id": run_id, **fields}, default=str))


class KillSwitch:
    def __init__(self, *, iam, lam, scheduler, s3, env: dict[str, str], sleep=time.sleep) -> None:
        self.iam, self.lam, self.scheduler, self.s3, self.sleep = iam, lam, scheduler, s3, sleep
        self.policy_arn = env["KILL_SWITCH_POLICY_ARN"]
        self.api_role = env["API_ROLE_NAME"]
        self.api_function = env["API_FUNCTION_NAME"]
        self.api_concurrency = int(env["API_RESERVED_CONCURRENCY"])
        self.schedules = [s for s in env.get("SCHEDULE_NAMES", "").split(",") if s]
        self.bucket = env["LAKE_BUCKET"]

    # --- state ---------------------------------------------------------------------------------
    def policy_attached(self) -> bool:
        pages = self.iam.get_paginator("list_attached_role_policies").paginate(RoleName=self.api_role)
        return any(p["PolicyArn"] == self.policy_arn for page in pages for p in page["AttachedPolicies"])

    def _state(self) -> dict | None:
        try:
            return json.loads(self.s3.get_object(Bucket=self.bucket, Key=STATE_KEY)["Body"].read())
        except self.s3.exceptions.NoSuchKey:
            return None

    def _put(self, key: str, body: dict) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=json.dumps(body).encode(), ContentType="application/json",
                           CacheControl="no-cache")

    def _set_schedule(self, name: str, state: str) -> bool:
        """Set ENABLED/DISABLED; True when it changed. UpdateSchedule replaces the whole definition, so copy it."""
        current = self.scheduler.get_schedule(Name=name)
        if current["State"] == state:
            return False
        self.scheduler.update_schedule(**{k: current[k] for k in SCHEDULE_FIELDS if current.get(k) is not None}, State=state)
        return True

    # --- actions -------------------------------------------------------------------------------
    def engage(self, run_id: str, state: dict | None) -> dict:
        disabled = list((state or {}).get("disabled_schedules", []))
        for name in self.schedules:
            if self._set_schedule(name, "DISABLED"):
                disabled.append(name)
        self.lam.put_function_concurrency(FunctionName=self.api_function, ReservedConcurrentExecutions=0)
        since = (state or {}).get("since") or datetime.now(UTC).isoformat(timespec="seconds")
        self._put(STATE_KEY, {"since": since, "disabled_schedules": sorted(set(disabled))})
        self._put(FLAG_KEY, {"active": True, "since": since})
        _emit(run_id, "kill_switch_engaged", since=since, schedules_disabled=len(set(disabled)))
        return {"status": "engaged", "since": since}

    def lift(self, run_id: str, state: dict) -> dict:
        self.lam.put_function_concurrency(FunctionName=self.api_function, ReservedConcurrentExecutions=self.api_concurrency)
        for name in state.get("disabled_schedules", []):
            self._set_schedule(name, "ENABLED")
        self.s3.delete_object(Bucket=self.bucket, Key=FLAG_KEY)
        self.s3.delete_object(Bucket=self.bucket, Key=STATE_KEY)
        _emit(run_id, "kill_switch_lifted", since=state.get("since"), schedules_enabled=len(state.get("disabled_schedules", [])))
        return {"status": "lifted"}

    def sync(self, run_id: str, *, retries: int = 0, wait_s: float = 15) -> dict:
        """Reconcile with the deny policy. `retries`: re-check a detached policy (Budgets may notify before IAM settles)."""
        attached = self.policy_attached()
        for _ in range(retries):
            if attached:
                break
            self.sleep(wait_s)
            attached = self.policy_attached()
        state = self._state()
        if attached:
            return self.engage(run_id, state)
        if state is not None:
            return self.lift(run_id, state)
        _emit(run_id, "kill_switch_idle")
        return {"status": "idle"}


def handler(event, context):  # pragma: no cover - thin AWS wiring, logic tested through KillSwitch
    import boto3

    run_id = f"ks-{uuid.uuid4().hex[:12]}"
    from_sns = any(r.get("EventSource") == "aws:sns" for r in (event or {}).get("Records", []))
    ks = KillSwitch(iam=boto3.client("iam"), lam=boto3.client("lambda"), scheduler=boto3.client("scheduler"),
                    s3=boto3.client("s3"), env=dict(os.environ))
    return ks.sync(run_id, retries=3 if from_sns else 0)
