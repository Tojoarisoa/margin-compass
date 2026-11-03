"""Model registry (PLAN.md §6.2 Stage 4): versions, metrics, and aliases.

Artifacts and model cards live in object storage (local folder or S3 `models/`). The index lives in a
JSON file locally and in the DynamoDB `core` table in AWS (ADR-011). Same interface for both.
"""

from .base import ModelVersion, Registry, should_promote
from .dynamodb import DynamoRegistry
from .file import FileRegistry

__all__ = ["DynamoRegistry", "FileRegistry", "ModelVersion", "Registry", "should_promote"]
