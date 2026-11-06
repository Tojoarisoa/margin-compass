#!/usr/bin/env python3
"""CI cost gate (PLAN.md §11.3 guardrail 8, §15 PR pipeline steps 7-8).

Reads synthesized templates (cdk.out) and fails when:
  1. a resource type isn't in the cost catalog below (a new service needs a priced entry first);
  2. a forbidden type appears (PLAN.md §11.2; also enforced at synth by ForbiddenResourceGuard);
  3. CloudWatch alarms > 10 (§14), action-enabled budgets > 2 (VER-06), or DynamoDB is on-demand /
     above the 25 RCU / 25 WCU free capacity;
  4. the worst-case monthly estimate exceeds the $3 alert threshold (§11);
  5. infra/cost-baseline.json doesn't match the synth (cost changes must be committed visibly).
It prints a Markdown summary, including the delta against a baseline from main (--compare).

  uv run python scripts/cost_gate.py --cdk-out cdk.out [--compare main-baseline.json] [--update]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from margin_compass_infra.guardrails import ALLOWED_BY_ADR, FORBIDDEN_TYPES  # noqa: E402

BASELINE = Path(__file__).resolve().parents[1] / "cost-baseline.json"
ALERT_USD = Decimal("3.00")
MAX_ALARMS, MAX_ACTION_BUDGETS, FREE_RCU, FREE_WCU = 10, 2, 25, 25

# Steady-state USD per resource per month at M1 usage (PLAN.md §11.1, VER-02/03). Zero = inside an
# always-free allowance or no charge for the resource itself.
CATALOG: dict[str, tuple[Decimal, str]] = {
    "AWS::S3::Bucket": (Decimal("0.10"), "storage + requests, ~1-3 GB (§11.1)"),
    "AWS::S3::BucketPolicy": (Decimal(0), ""),
    "AWS::S3Vectors::VectorBucket": (Decimal("0.01"), "thousands of vectors (VER-03)"),
    "AWS::S3Vectors::Index": (Decimal(0), "billed per bucket storage and queries"),
    "AWS::Lambda::Function": (Decimal(0), "free tier; container images priced separately"),
    "AWS::Lambda::Url": (Decimal(0), ""), "AWS::Lambda::Permission": (Decimal(0), ""),
    "AWS::Lambda::EventInvokeConfig": (Decimal(0), ""), "AWS::Lambda::LayerVersion": (Decimal(0), ""),
    "AWS::Logs::LogGroup": (Decimal("0.01"), "7-day retention"),
    "AWS::DynamoDB::Table": (Decimal(0), "provisioned within 25 RCU/WCU (checked)"),
    "AWS::CloudFront::Distribution": (Decimal(0), "always-free 1 TB / 10M requests"),
    "AWS::CloudFront::CachePolicy": (Decimal(0), ""), "AWS::CloudFront::OriginRequestPolicy": (Decimal(0), ""),
    "AWS::CloudFront::ResponseHeadersPolicy": (Decimal(0), ""), "AWS::CloudFront::OriginAccessControl": (Decimal(0), ""),
    "AWS::CertificateManager::Certificate": (Decimal(0), "public ACM certificates are free"),
    "AWS::CloudWatch::Alarm": (Decimal(0), "first 10 free (checked)"),
    "AWS::StepFunctions::StateMachine": (Decimal(0), "Standard, ~4 transitions/run (4,000 free)"),
    "AWS::Scheduler::Schedule": (Decimal(0), "< 100 invocations"),
    "AWS::SNS::Topic": (Decimal(0), ""), "AWS::SNS::TopicPolicy": (Decimal(0), ""), "AWS::SNS::Subscription": (Decimal(0), ""),
    "AWS::Budgets::Budget": (Decimal(0), "monitoring is free"),
    "AWS::Budgets::BudgetsAction": (Decimal(0), "first 2 action-enabled budgets free (checked)"),
    "AWS::CE::AnomalyMonitor": (Decimal(0), ""), "AWS::CE::AnomalySubscription": (Decimal(0), ""),
    "AWS::BCMDataExports::Export": (Decimal(0), "export is free; storage counted in its bucket"),
    "AWS::IAM::Role": (Decimal(0), ""), "AWS::IAM::Policy": (Decimal(0), ""), "AWS::IAM::ManagedPolicy": (Decimal(0), ""),
    "AWS::IAM::OIDCProvider": (Decimal(0), ""),
    "AWS::CDK::Metadata": (Decimal(0), ""),
}
ECR_PER_IMAGE = Decimal("0.04")  # ~0.3-0.4 GB compressed x $0.10/GB-month
LLM_ONLINE_CAP = Decimal("1.50")  # agents/mc_agents/guard.py Caps.monthly_usd (a test keeps them equal)
EMBEDDINGS = Decimal("0.01")      # < 100k tokens per run at $0.02/1M (ADR-003), mostly skipped by hash


def load(cdk_out: Path) -> dict[str, dict]:
    return {p.name.removesuffix(".template.json"): json.loads(p.read_text())
            for p in sorted(cdk_out.glob("*.template.json"))}


def analyse(templates: dict[str, dict]) -> dict:
    counts: dict[str, Counter] = {s: Counter(r["Type"] for r in t.get("Resources", {}).values()) for s, t in templates.items()}
    errors, lines = [], []
    rcu = wcu = alarms = actions = images = 0
    for stack, t in templates.items():
        for logical, r in t.get("Resources", {}).items():
            typ, props = r["Type"], r.get("Properties", {})
            if typ.startswith("Custom::"):
                errors.append(f"{stack}/{logical}: custom resource {typ} needs a review and a catalog entry")
            elif typ not in CATALOG:
                errors.append(f"{stack}/{logical}: {typ} has no cost catalog entry")
            if typ not in ALLOWED_BY_ADR:
                for key, reason in FORBIDDEN_TYPES.items():
                    if typ == key or (key.endswith("::") and typ.startswith(key)):
                        errors.append(f"{stack}/{logical}: forbidden {typ} ({reason})")
            if typ == "AWS::DynamoDB::Table":
                if props.get("BillingMode") == "PAY_PER_REQUEST":
                    errors.append(f"{stack}/{logical}: DynamoDB on-demand mode is forbidden")
                tp = props.get("ProvisionedThroughput", {})
                rcu += int(tp.get("ReadCapacityUnits", 0))
                wcu += int(tp.get("WriteCapacityUnits", 0))
            alarms += typ == "AWS::CloudWatch::Alarm"
            actions += typ == "AWS::Budgets::BudgetsAction"
            images += typ == "AWS::Lambda::Function" and props.get("PackageType") == "Image"
    if alarms > MAX_ALARMS:
        errors.append(f"{alarms} CloudWatch alarms (limit {MAX_ALARMS}, §14)")
    if actions > MAX_ACTION_BUDGETS:
        errors.append(f"{actions} budget actions (first {MAX_ACTION_BUDGETS} free, VER-06)")
    if rcu > FREE_RCU or wcu > FREE_WCU:
        errors.append(f"DynamoDB provisioned {rcu} RCU / {wcu} WCU exceeds the free {FREE_RCU}/{FREE_WCU}")

    by_type = Counter()
    for c in counts.values():
        by_type.update(c)
    for typ, n in sorted(by_type.items()):
        unit = CATALOG.get(typ, (Decimal(0), ""))[0]
        if unit:
            lines.append((f"{typ} × {n}", unit * n))
    lines += [(f"ECR container images × {images}", ECR_PER_IMAGE * images),
              ("Bedrock LLM (online cap, enforced in code)", LLM_ONLINE_CAP), ("Bedrock embeddings", EMBEDDINGS)]
    total = sum((v for _, v in lines), Decimal(0))
    if total > ALERT_USD:
        errors.append(f"worst-case estimate ${total} exceeds the ${ALERT_USD} alert threshold")
    return {"counts": {s: dict(sorted(c.items())) for s, c in counts.items()}, "lines": lines, "total": total,
            "alarms": alarms, "rcu": rcu, "wcu": wcu, "budget_actions": actions, "images": images, "errors": errors}


def baseline_of(a: dict) -> dict:
    return {"total_usd": str(a["total"]), "stacks": a["counts"]}


def delta(old: dict, new: dict) -> list[str]:
    rows = []
    stacks = sorted(set(old.get("stacks", {})) | set(new["stacks"]))
    for s in stacks:
        o, n = old.get("stacks", {}).get(s, {}), new["stacks"].get(s, {})
        for typ in sorted(set(o) | set(n)):
            if o.get(typ, 0) != n.get(typ, 0):
                rows.append(f"| {s} | {typ} | {o.get(typ, 0)} | {n.get(typ, 0)} |")
    return rows


def report(a: dict, compare: dict | None) -> str:
    out = ["## Cost gate", "", f"Worst-case monthly estimate: **${a['total']}** (alert ${ALERT_USD}, ceiling $5).", "",
           "| Line | $/month |", "| --- | --- |"]
    out += [f"| {k} | {v} |" for k, v in a["lines"]]
    out += ["", f"Alarms {a['alarms']}/{MAX_ALARMS} · budget actions {a['budget_actions']}/{MAX_ACTION_BUDGETS} · "
                f"DynamoDB {a['rcu']}/{FREE_RCU} RCU, {a['wcu']}/{FREE_WCU} WCU", ""]
    if compare is not None:
        rows = delta(compare, baseline_of(a))
        old_total = Decimal(compare.get("total_usd", "0"))
        out += [f"Delta vs main: **{a['total'] - old_total:+} $/month**", ""]
        out += (["| Stack | Type | main | this PR |", "| --- | --- | --- | --- |"] + rows) if rows else ["No resource changes vs main."]
        out.append("")
    out += ([f"**Failed:** {e}" for e in a["errors"]] or ["**Passed.**"])
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cdk-out", type=Path, default=Path("cdk.out"))
    p.add_argument("--compare", type=Path, help="baseline JSON from main")
    p.add_argument("--update", action="store_true", help="rewrite infra/cost-baseline.json from this synth")
    args = p.parse_args(argv)
    templates = load(args.cdk_out)
    if not templates:
        print(f"no templates in {args.cdk_out}: run cdk synth first", file=sys.stderr)
        return 2
    a = analyse(templates)
    current = baseline_of(a)
    if args.update:
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    elif not BASELINE.exists() or json.loads(BASELINE.read_text()) != current:
        a["errors"].append("infra/cost-baseline.json is out of date: run `uv run python scripts/cost_gate.py --update` and commit it")
    compare = json.loads(args.compare.read_text()) if args.compare and args.compare.exists() else None
    print(report(a, compare))
    return 1 if a["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
