from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/cobol-openapi-generator/scripts"
sys.path.insert(0, str(SCRIPTS))

import copybook_parser  # noqa: E402
from copybook_parser import CopybookParser, Field, parse_copybook  # noqa: E402


@pytest.fixture(autouse=True)
def _repository_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)


@pytest.fixture
def copybooks() -> Path:
    return ROOT / "tests/fixtures/copybooks"


def _walk_names(parsed: copybook_parser.ParsedCopybook) -> list[str]:
    return [item.name for item in parsed.walk()]


def test_parse_request_copybook(copybooks: Path) -> None:
    parsed = parse_copybook(copybooks / "customer-request.cbl")
    names = _walk_names(parsed)
    assert "CUSTOMER-REQUEST" in names
    assert "CUSTOMER-ID" in names
    assert "TYPE-INDIVIDUAL" in names
    assert not [item for item in parsed.diagnostics if item.severity == "error"]
    root = parsed.fields[0]
    assert root.is_group
    customer_id = next(item for item in root.walk() if item.name == "CUSTOMER-ID")
    assert customer_id.json_type() == "integer"
    assert customer_id.digit_count() == 9
    customer_type = next(item for item in root.walk() if item.name == "CUSTOMER-TYPE")
    assert customer_type.max_length() == 1
    conditions = [item for item in customer_type.children if item.is_condition]
    assert {item.name for item in conditions} == {"TYPE-INDIVIDUAL", "TYPE-BUSINESS"}
    assert customer_type.is_group is False
    address = next(item for item in root.walk() if item.name == "CUSTOMER-ADDRESS")
    assert address.is_array
    assert address.occurs_min == 3
    assert address.occurs_max == 3


def test_parse_response_copybook_decimals_and_odo(copybooks: Path) -> None:
    parsed = parse_copybook(copybooks / "customer-response.cbl")
    balance = next(item for item in parsed.walk() if item.name == "ACCOUNT-BALANCE")
    assert balance.json_type() == "number"
    assert balance.json_format() == "decimal"
    assert balance.digit_count() == 9
    assert balance.decimal_scale() == 2
    item = next(entry for entry in parsed.walk() if entry.name == "CUSTOMER-ITEM")
    assert item.is_array
    assert item.occurs_min == 0
    assert item.occurs_max == 20
    assert item.depending_on == "ITEM-COUNT"
    assert any(diagnostic.code == "odo-counter" for diagnostic in parsed.diagnostics)


def test_parse_copybook_expands_copy(copybooks: Path) -> None:
    parsed = CopybookParser(copybook_paths=[copybooks]).parse(copybooks / "with-copy.cbl")
    names = _walk_names(parsed)
    assert names.index("HEADER") < names.index("COMMON-CODE") < names.index("TRAILER")
    assert parsed.included
    assert Path(parsed.included[0]).name == "copy-common.cpy"
    assert not [item for item in parsed.diagnostics if item.severity == "error"]


def test_missing_copy_member_is_an_error(copybooks: Path, tmp_path: Path) -> None:
    source = tmp_path / "missing-copy.cbl"
    source.write_text("       01  ROOT.\n           COPY DOES-NOT-EXIST.\n", encoding="utf-8")
    parsed = CopybookParser(copybook_paths=[copybooks]).parse(source)
    assert any(item.code == "missing-copy-member" and item.severity == "error" for item in parsed.diagnostics)


def test_copy_cycle_is_reported(tmp_path: Path) -> None:
    first = tmp_path / "first.cpy"
    second = tmp_path / "second.cpy"
    first.write_text("       01  FIRST.\n           COPY SECOND.\n", encoding="utf-8")
    second.write_text("       01  SECOND.\n           COPY FIRST.\n", encoding="utf-8")
    parsed = CopybookParser(copybook_paths=[tmp_path]).parse(first)
    assert any(item.code == "copy-cycle" for item in parsed.diagnostics)


def test_copy_replacing_is_reported(copybooks: Path, tmp_path: Path) -> None:
    source = tmp_path / "replacing.cbl"
    source.write_text("       01  ROOT.\n           COPY COMMON REPLACING ==A== BY ==B==.\n", encoding="utf-8")
    parsed = CopybookParser(copybook_paths=[copybooks]).parse(source)
    assert any(item.code == "copy-replacing" for item in parsed.diagnostics)


def test_redefines_is_flagged(copybooks: Path) -> None:
    parsed = parse_copybook(copybooks / "redefines.cbl")
    bank = next(item for item in parsed.walk() if item.name == "BANK-DATA")
    assert bank.redefines == "CARD-DATA"
    assert any(item.code == "ambiguous-redefines" for item in parsed.diagnostics)


def test_free_format_comments_and_sql() -> None:
    text = """
* free-format comment
01 ROOT.
  05 ID PIC 9(4).
  *> inline comment
  05 NAME PIC X(10).
  EXEC SQL SELECT 1 INTO :X END-EXEC.
  05 AMOUNT PIC 9(20).99.
"""
    parsed = CopybookParser(free_format=True).parse_text(text, source="free.cbl")
    names = _walk_names(parsed)
    assert "ROOT" in names
    assert "ID" in names
    assert any(item.code == "embedded-sql-or-cics" for item in parsed.diagnostics)
    assert any(item.code == "real-decimal" for item in parsed.diagnostics)


def test_unsupported_usage_and_unknown_group() -> None:
    text = """
       01  ROOT.
           05  PTR                  USAGE POINTER.
           05  EMPTY.
           05  BAD                  PIC 9(9).
               88  BAD-VALUE        VALUE 'X'.
"""
    parsed = CopybookParser(free_format=True).parse_text(text)
    ptr = next(item for item in parsed.walk() if item.name == "PTR")
    assert ptr.json_type() == "unsupported"
    empty = next(item for item in parsed.walk() if item.name == "EMPTY")
    assert empty.json_type() == "unknown"
    assert {item.code for item in parsed.diagnostics} >= {
        "unsupported-usage",
        "unknown-type",
        "group-without-children",
    }


def test_level_66_and_77_and_orphan_88() -> None:
    text = """
       01  ROOT.
           05  ITEM-A               PIC X(2).
           05  ITEM-B               PIC X(3).
           66  RENAMED              RENAMES ITEM-A THRU ITEM-B.
       77  STANDALONE               PIC X(1).
"""
    parsed = CopybookParser(free_format=True).parse_text(text)
    assert any(item.code == "renames-66" for item in parsed.diagnostics)
    assert any(item.code == "level-77" for item in parsed.diagnostics)
    orphan = CopybookParser(free_format=True).parse_text("       88  LONELY VALUE 'Y'.\n")
    assert any(item.code == "orphan-88" for item in orphan.diagnostics)


def test_parse_missing_and_unreadable(copybooks: Path) -> None:
    parsed = parse_copybook(copybooks / "does-not-exist.cbl")
    assert any(item.code == "missing-copybook" for item in parsed.diagnostics)
    assert parse_copybook(copybooks).diagnostics


def test_parse_text_preserves_root_and_to_dict(copybooks: Path) -> None:
    parsed = parse_copybook(copybooks / "customer-request.cbl")
    data = parsed.to_dict(include_source=True)
    assert data["fields"]
    root = data["fields"][0]
    assert root["name"] == "CUSTOMER-REQUEST"
    assert root["kind"] == "group"
    assert root["source"].endswith("customer-request.cbl")
    customer_id = root["children"][0]
    assert customer_id["jsonType"] == "integer"
    assert customer_id["line"] > 0


def test_field_helpers() -> None:
    field = Field(level=5, name="VALUE-FIELD", pic="S9(5)V99", usage="DISPLAY")
    assert field.json_type() == "number"
    assert field.digit_count() == 7
    assert field.decimal_scale() == 2
    assert field.max_length() == 7
    assert field.to_dict()["kind"] == "field"
    filler = Field(level=5, name="FILLER", pic="X")
    assert filler.is_filler
    group = Field(level=1, name="GROUP", children=[Field(level=5, name="A", pic="X")])
    assert group.is_group
    assert group.json_type() == "object"


def test_cli_json_and_human_output(copybooks: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = str(copybooks / "customer-request.cbl")
    assert copybook_parser.main([source, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"].endswith("customer-request.cbl")
    assert copybook_parser.main([source]) == 0
    output = capsys.readouterr().out
    assert "Copybook:" in output
    assert "CUSTOMER-REQUEST" in output
    assert copybook_parser.main([str(copybooks / "does-not-exist.cbl"), "--json"]) == 1
    error_payload = json.loads(capsys.readouterr().out)
    assert any(item["severity"] == "error" for item in error_payload["diagnostics"])
