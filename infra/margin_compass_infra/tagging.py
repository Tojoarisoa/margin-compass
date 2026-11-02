"""Mandatory tags on every taggable resource (AGENTS.md rule 1)."""

from __future__ import annotations

import aws_cdk as cdk
from constructs import IConstruct

REQUIRED_TAG_KEYS = ("project", "env", "stage", "owner", "cost-center")


def apply_tags(scope: IConstruct, *, project: str, env: str, stage: str, owner: str, cost_center: str) -> None:
    values = {"project": project, "env": env, "stage": stage, "owner": owner, "cost-center": cost_center}
    for key in REQUIRED_TAG_KEYS:
        cdk.Tags.of(scope).add(key, values[key])
