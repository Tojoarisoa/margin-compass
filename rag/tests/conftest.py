from pathlib import Path

import pytest

KNOWLEDGE = Path(__file__).resolve().parents[2] / "knowledge"


@pytest.fixture
def knowledge_dir() -> Path:
    return KNOWLEDGE
