"""The CI cost gate fails on unpriced, forbidden, or over-budget infrastructure (PLAN.md §11.3 guardrail 8)."""

from __future__ import annotations

import ast
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cost_gate.py"
spec = importlib.util.spec_from_file_location("cost_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def _tpl(*resources):
    return {"S": {"Resources": {f"R{i}": r for i, r in enumerate(resources)}}}


def test_clean_template_passes():
    a = gate.analyse(_tpl({"Type": "AWS::S3::Bucket"}, {"Type": "AWS::Lambda::Function", "Properties": {"PackageType": "Image"}}))
    assert a["errors"] == [] and a["images"] == 1
    assert a["total"] == Decimal("0.10") + gate.ECR_PER_IMAGE + gate.LLM_ONLINE_CAP + gate.EMBEDDINGS


@pytest.mark.parametrize("resource, message", [
    ({"Type": "AWS::SQS::Queue"}, "no cost catalog entry"),
    ({"Type": "AWS::EC2::NatGateway"}, "forbidden"),
    ({"Type": "Custom::Anything"}, "custom resource"),
    ({"Type": "AWS::DynamoDB::Table", "Properties": {"BillingMode": "PAY_PER_REQUEST"}}, "on-demand"),
    ({"Type": "AWS::DynamoDB::Table", "Properties": {"ProvisionedThroughput": {"ReadCapacityUnits": 30, "WriteCapacityUnits": 1}}}, "RCU"),
])
def test_gate_failures(resource, message):
    assert any(message in e for e in gate.analyse(_tpl(resource))["errors"])


def test_alarm_and_budget_action_limits():
    a = gate.analyse(_tpl(*[{"Type": "AWS::CloudWatch::Alarm"}] * 11, *[{"Type": "AWS::Budgets::BudgetsAction"}] * 3))
    assert any("alarms" in e for e in a["errors"]) and any("budget actions" in e for e in a["errors"])


def test_over_threshold_estimate_fails(monkeypatch):
    monkeypatch.setattr(gate, "LLM_ONLINE_CAP", Decimal("2.90"))
    assert any("alert threshold" in e for e in gate.analyse(_tpl({"Type": "AWS::S3::Bucket"}))["errors"])


def test_delta_lists_changed_types():
    old = {"stacks": {"S": {"AWS::S3::Bucket": 1}}, "total_usd": "1.70"}
    new = gate.baseline_of(gate.analyse(_tpl({"Type": "AWS::S3::Bucket"}, {"Type": "AWS::S3::Bucket"})))
    assert gate.delta(old, new) == ["| S | AWS::S3::Bucket | 1 | 2 |"]
    assert "Delta vs main" in gate.report(gate.analyse(_tpl({"Type": "AWS::S3::Bucket"})), old)


def test_llm_line_matches_the_agent_api_cap():
    guard = Path(__file__).resolve().parents[2] / "agents" / "mc_agents" / "guard.py"
    caps = next(n for n in ast.parse(guard.read_text()).body if isinstance(n, ast.ClassDef) and n.name == "Caps")
    monthly = next(s for s in caps.body if isinstance(s, ast.AnnAssign) and s.target.id == "monthly_usd")
    assert Decimal(monthly.value.args[0].value) == gate.LLM_ONLINE_CAP


def test_committed_baseline_is_valid_json():
    b = json.loads(gate.BASELINE.read_text())
    assert Decimal(b["total_usd"]) <= gate.ALERT_USD and "mc-dev-web" in b["stacks"]
