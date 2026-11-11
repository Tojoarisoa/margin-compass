"""Kill-switch handler (G1, PLAN.md §11.3): reconcile the app with the deny policy (fakes, no AWS)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "functions" / "kill_switch"))
from handler import FLAG_KEY, STATE_KEY, KillSwitch  # noqa: E402

POLICY = "arn:aws:iam::123456789012:policy/mc-shared-foundation-kill-switch-deny"
ENV = {"KILL_SWITCH_POLICY_ARN": POLICY, "API_ROLE_NAME": "mc-dev-web-api", "API_FUNCTION_NAME": "mc-dev-web-api",
       "API_RESERVED_CONCURRENCY": "5", "SCHEDULE_NAMES": "mc-dev-data-nightly,mc-dev-data-telemetry", "LAKE_BUCKET": "lake"}


class NoSuchKey(Exception):
    pass


class FakeAws:
    def __init__(self, attached: list[bool], schedules: dict[str, str]) -> None:
        self.attached = attached  # one answer per check; the last repeats
        self.schedules = schedules
        self.objects: dict[str, bytes] = {}
        self.concurrency: list[int] = []
        self.updates: list[dict] = []
        self.exceptions = type("E", (), {"NoSuchKey": NoSuchKey})

    # iam
    def get_paginator(self, name):
        assert name == "list_attached_role_policies"
        outer = self

        class P:
            def paginate(self, RoleName):
                assert RoleName == "mc-dev-web-api"
                on = outer.attached.pop(0) if len(outer.attached) > 1 else outer.attached[0]
                return [{"AttachedPolicies": [{"PolicyArn": POLICY}] if on else []}]
        return P()

    # lambda
    def put_function_concurrency(self, FunctionName, ReservedConcurrentExecutions):
        assert FunctionName == "mc-dev-web-api"
        self.concurrency.append(ReservedConcurrentExecutions)

    # scheduler
    def get_schedule(self, Name):
        return {"Name": Name, "GroupName": "default", "State": self.schedules[Name], "ScheduleExpression": "cron(0 2 * * ? *)",
                "FlexibleTimeWindow": {"Mode": "OFF"}, "Target": {"Arn": "arn:t", "RoleArn": "arn:r"}, "Arn": "ignored",
                "CreationDate": "ignored", "KmsKeyArn": None}

    def update_schedule(self, **kw):
        assert "Arn" not in kw and "CreationDate" not in kw and "KmsKeyArn" not in kw
        assert kw["Target"] == {"Arn": "arn:t", "RoleArn": "arn:r"} and kw["ScheduleExpression"]
        self.updates.append(kw)
        self.schedules[kw["Name"]] = kw["State"]

    # s3
    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **_):
        assert Bucket == "lake"
        self.objects[Key] = Body

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


def ks(aws: FakeAws) -> KillSwitch:
    return KillSwitch(iam=aws, lam=aws, scheduler=aws, s3=aws, env=ENV, sleep=lambda s: None)


def test_idle_when_policy_detached_and_nothing_engaged():
    aws = FakeAws([False], {"mc-dev-data-nightly": "ENABLED", "mc-dev-data-telemetry": "DISABLED"})
    assert ks(aws).sync("r")["status"] == "idle"
    assert aws.concurrency == [] and aws.updates == [] and aws.objects == {}


def test_engage_pauses_api_disables_enabled_schedules_and_raises_public_flag():
    aws = FakeAws([True], {"mc-dev-data-nightly": "ENABLED", "mc-dev-data-telemetry": "DISABLED"})
    assert ks(aws).sync("r")["status"] == "engaged"
    assert aws.concurrency == [0]
    assert aws.schedules == {"mc-dev-data-nightly": "DISABLED", "mc-dev-data-telemetry": "DISABLED"}
    flag = json.loads(aws.objects[FLAG_KEY])
    assert flag["active"] is True and set(flag) == {"active", "since"}  # public: no internal names
    assert json.loads(aws.objects[STATE_KEY])["disabled_schedules"] == ["mc-dev-data-nightly"]


def test_engage_twice_keeps_since_and_what_it_disabled():
    aws = FakeAws([True], {"mc-dev-data-nightly": "ENABLED", "mc-dev-data-telemetry": "DISABLED"})
    first = ks(aws).sync("r")
    second = ks(aws).sync("r")
    assert second["since"] == first["since"]
    assert json.loads(aws.objects[STATE_KEY])["disabled_schedules"] == ["mc-dev-data-nightly"]


def test_lift_restores_only_what_it_changed():
    aws = FakeAws([True], {"mc-dev-data-nightly": "ENABLED", "mc-dev-data-telemetry": "DISABLED"})
    ks(aws).sync("r")
    aws.attached = [False]
    assert ks(aws).sync("r")["status"] == "lifted"
    assert aws.concurrency == [0, 5]
    assert aws.schedules == {"mc-dev-data-nightly": "ENABLED", "mc-dev-data-telemetry": "DISABLED"}
    assert aws.objects == {}


def test_sns_trigger_rechecks_a_policy_that_is_not_attached_yet():
    aws = FakeAws([False, False, True], {"mc-dev-data-nightly": "DISABLED", "mc-dev-data-telemetry": "DISABLED"})
    assert ks(aws).sync("r", retries=3)["status"] == "engaged"


@pytest.mark.parametrize("retries", [0, 3])
def test_alert_without_the_policy_changes_nothing(retries):
    aws = FakeAws([False], {"mc-dev-data-nightly": "ENABLED", "mc-dev-data-telemetry": "ENABLED"})
    assert ks(aws).sync("r", retries=retries)["status"] == "idle"
    assert aws.updates == [] and aws.concurrency == []
