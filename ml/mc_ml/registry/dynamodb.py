from __future__ import annotations

import json

from .base import ModelVersion, Registry


class DynamoRegistry(Registry):
    """AWS registry in the single-table DynamoDB `core` table (ADR-011).

    Items: PK = "MODEL#<name>", SK = "VERSION#<version>" (metrics, URIs, lineage) or "ALIAS#<alias>".
    Writes are conditional, so registering an existing version is a no-op.
    """

    def __init__(self, table_name: str, client=None) -> None:
        import boto3

        self.table = table_name
        self.client = client or boto3.client("dynamodb")

    @staticmethod
    def _pk(model_name: str) -> dict:
        return {"S": f"MODEL#{model_name}"}

    def get_version(self, model_name: str, version: str) -> ModelVersion | None:
        item = self.client.get_item(
            TableName=self.table, Key={"PK": self._pk(model_name), "SK": {"S": f"VERSION#{version}"}}, ConsistentRead=True
        ).get("Item")
        return ModelVersion(**json.loads(item["body"]["S"])) if item else None

    def register(self, mv: ModelVersion) -> bool:
        from dataclasses import asdict

        try:
            self.client.put_item(
                TableName=self.table,
                Item={
                    "PK": self._pk(mv.model_name),
                    "SK": {"S": f"VERSION#{mv.version}"},
                    "body": {"S": json.dumps(asdict(mv), sort_keys=True)},
                },
                ConditionExpression="attribute_not_exists(SK)",
            )
            return True
        except self.client.exceptions.ConditionalCheckFailedException:
            return False

    def get_alias(self, model_name: str, alias: str) -> str | None:
        item = self.client.get_item(
            TableName=self.table, Key={"PK": self._pk(model_name), "SK": {"S": f"ALIAS#{alias}"}}, ConsistentRead=True
        ).get("Item")
        return item["version"]["S"] if item else None

    def set_alias(self, model_name: str, alias: str, version: str) -> None:
        if self.get_version(model_name, version) is None:
            raise KeyError(f"{model_name} has no version {version}")
        self.client.put_item(
            TableName=self.table,
            Item={"PK": self._pk(model_name), "SK": {"S": f"ALIAS#{alias}"}, "version": {"S": version}},
        )
