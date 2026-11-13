from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/cobol-openapi-generator/scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(autouse=True)
def _repository_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def scripts_dir() -> Path:
    return SCRIPTS


@pytest.fixture
def copybooks_dir() -> Path:
    return ROOT / "tests/fixtures/copybooks"


@pytest.fixture
def contracts_dir() -> Path:
    return ROOT / "tests/fixtures/contracts"
