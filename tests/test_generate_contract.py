from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/cobol-openapi-generator/scripts"))

import generate_contract  # noqa: E402
from generate_contract import (  # noqa: E402
    ContractBuilder,
    GenerationError,
    _camel_case,
    _pascal_case,
    _release_tuple,
    generate,
)


def load_valid_spec() -> dict:
    return json.loads((ROOT / "tests/fixtures/contracts/valid-spec.json").read_text(encoding="utf-8"))


def write_spec(tmp_path: Path, spec: dict) -> Path:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def build(spec: dict, copybook_paths: list[Path] | None = None) -> generate_contract.GenerationResult:
    builder = ContractBuilder(
        spec,
        copybook_paths=copybook_paths or [ROOT / "tests/fixtures/copybooks"],
    )
    return builder.build()


def test_generate_both_formats(tmp_path: Path) -> None:
    spec = load_valid_spec()
    result = generate(
        write_spec(tmp_path, spec),
        out_dir=tmp_path / "out",
        copybook_paths=[ROOT / "tests/fixtures/copybooks"],
    )
    out = tmp_path / "out"
    assert result.output_paths["swagger"] == out / "swagger.json"
    assert result.output_paths["openapi"] == out / "openapi.yml"
    assert (out / "mapping-analysis.md").is_file()
    assert (out / "generation-report.md").is_file()
    swagger = json.loads((out / "swagger.json").read_text(encoding="utf-8"))
    openapi = (out / "openapi.yml").read_text(encoding="utf-8")
    assert swagger["swagger"] == "2.0"
    assert swagger["basePath"] == "/api/customer"
    assert swagger["definitions"]
    assert "#/definitions/" in json.dumps(swagger)
    assert "#/components/schemas/" in openapi
    assert "openapi: 3.0.3" in openapi
    assert "url: https://api.example.com/api/customer" in openapi
    assert "404" in swagger["paths"]["/customers/{customerId}"]["put"]["responses"]
    assert result.report
    assert "SHA-256" in result.report
    assert "toolchain-required" in result.report
    assert "needs-review" in result.report
    mapping = (out / "mapping-analysis.md").read_text(encoding="utf-8")
    assert "| COBOL field | JSON path | JSON type | Required | Evidence | Status | Notes |" in mapping
    assert "| CUSTOMER-ID |" in mapping
    assert "| ITEM-COUNT |" in mapping
    assert "enum" in mapping
    for row in result.mapping_rows:
        assert len(row.to_markdown().split(" | ")) == 7


def test_schema_content_and_decisions(tmp_path: Path) -> None:
    spec = load_valid_spec()
    result = build(spec)
    request_schema = result.swagger["definitions"]["UpdateCustomerRequest"]
    response_schema = result.swagger["definitions"]["UpdateCustomer200Response"]
    error_schema = result.swagger["definitions"]["UpdateCustomer404Response"]
    assert request_schema["properties"]["customerId"] == {"type": "integer", "format": "int32"}
    assert request_schema["properties"]["customerName"]["maxLength"] == 40
    assert request_schema["properties"]["customerType"]["enum"] == ["I", "B"]
    assert "required" in request_schema and "customerId" in request_schema["required"]
    balance = response_schema["properties"]["accountBalance"]
    assert balance["type"] == "number"
    assert balance["format"] == "decimal"
    assert balance["multipleOf"] == 0.01
    assert balance["minimum"] == -9999999.99
    assert balance["maximum"] == 9999999.99
    assert "itemCount" not in response_schema["properties"]
    assert response_schema["properties"]["customerItem"]["maxItems"] == 20
    assert error_schema["properties"]["errorDetail"]["minItems"] == 0
    report = result.report
    assert "ODO `ITEM-COUNT`: excluded" in report
    assert "Required `CUSTOMER-ID`" in report
    assert "Confirm CICS service mapping" in report


def test_format_selection(tmp_path: Path) -> None:
    spec = load_valid_spec()
    swagger_only = generate(
        write_spec(tmp_path, spec),
        out_dir=tmp_path / "swagger-only",
        copybook_paths=[ROOT / "tests/fixtures/copybooks"],
        output_format="swagger2",
    )
    assert set(swagger_only.output_paths) == {"swagger", "mapping", "report"}
    assert not (tmp_path / "swagger-only/openapi.yml").exists()
    openapi_only = generate(
        write_spec(tmp_path, spec),
        out_dir=tmp_path / "openapi-only",
        copybook_paths=[ROOT / "tests/fixtures/copybooks"],
        output_format="openapi3",
    )
    assert set(openapi_only.output_paths) == {"openapi", "mapping", "report"}
    assert not (tmp_path / "openapi-only/swagger.json").exists()


def test_output_directory_from_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    spec = load_valid_spec()
    spec["output"]["dir"] = "from-spec"
    for key in ("request",):
        spec[key]["copybook"] = str(ROOT / spec[key]["copybook"])
    for response in spec["responses"]:
        if response.get("copybook"):
            response["copybook"] = str(ROOT / response["copybook"])
    result = generate(write_spec(tmp_path, spec), copybook_paths=[ROOT / "tests/fixtures/copybooks"])
    assert (tmp_path / "from-spec/swagger.json").is_file()
    assert result.output_paths["mapping"].resolve().parent == (tmp_path / "from-spec").resolve()


def test_generate_missing_and_invalid_spec(tmp_path: Path) -> None:
    with pytest.raises(GenerationError, match="not found"):
        generate(tmp_path / "missing.json")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(GenerationError, match="Invalid JSON"):
        generate(invalid)
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(GenerationError, match="JSON object"):
        generate(array)


def test_invalid_spec_fixture_reports_all_errors(tmp_path: Path) -> None:
    spec = json.loads((ROOT / "tests/fixtures/contracts/invalid-spec.json").read_text(encoding="utf-8"))
    with pytest.raises(GenerationError) as error:
        generate(write_spec(tmp_path, spec))
    messages = " ".join(error.value.messages)
    assert "CUSTOMER-ID" in messages
    assert "head" in messages
    assert "2XX" in messages


def test_missing_request_response_and_success_errors(tmp_path: Path) -> None:
    spec = load_valid_spec()
    spec["request"] = {}
    spec["responses"] = []
    with pytest.raises(GenerationError) as error:
        build(spec)
    messages = " ".join(error.value.messages)
    assert "missing-request-copybook" not in messages
    assert "At least one response" in messages


def test_invalid_response_entries(tmp_path: Path) -> None:
    spec = load_valid_spec()
    spec["responses"] = ["bad", {"code": "2XX", "description": ""}]
    with pytest.raises(GenerationError) as error:
        build(spec)
    messages = " ".join(error.value.messages)
    assert "must be an object" in messages
    assert "Invalid response code" in messages
    assert "needs a description" in messages


def test_no_success_response(tmp_path: Path) -> None:
    spec = load_valid_spec()
    spec["responses"] = [{"code": "404", "description": "Missing"}]
    with pytest.raises(GenerationError, match="2xx"):
        build(spec)


def test_missing_copybooks(tmp_path: Path) -> None:
    spec = load_valid_spec()
    spec["request"]["copybook"] = "missing.cbl"
    spec["responses"][0]["copybook"] = "missing-response.cbl"
    with pytest.raises(GenerationError) as error:
        build(spec)
    messages = " ".join(error.value.messages)
    assert "request copybook not found" in messages
    assert "response 200 copybook not found" in messages


def test_empty_copybook_and_no_fields(tmp_path: Path) -> None:
    empty = tmp_path / "empty.cbl"
    empty.write_text("", encoding="utf-8")
    spec = load_valid_spec()
    spec["request"]["copybook"] = str(empty)
    with pytest.raises(GenerationError) as error:
        build(spec)
    messages = " ".join(error.value.messages)
    assert "No COBOL entries" in messages
    assert "No usable fields" in messages


def test_output_escape_and_overwrite_are_rejected(tmp_path: Path) -> None:
    spec = load_valid_spec()
    spec["output"]["swagger"] = "../escape.json"
    with pytest.raises(GenerationError, match="escapes"):
        generate(write_spec(tmp_path, spec), out_dir=tmp_path / "out", copybook_paths=[ROOT / "tests/fixtures/copybooks"])
    spec = load_valid_spec()
    source = write_spec(tmp_path, spec)
    spec["output"]["swagger"] = "spec.json"
    source.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(GenerationError, match="overwrite an input"):
        generate(source, out_dir=tmp_path, copybook_paths=[ROOT / "tests/fixtures/copybooks"])


def test_yaml_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(generate_contract, "yaml", None)
    with pytest.raises(GenerationError, match="PyYAML"):
        generate(
            write_spec(tmp_path, load_valid_spec()),
            out_dir=tmp_path / "out",
            copybook_paths=[ROOT / "tests/fixtures/copybooks"],
        )


def test_release_and_naming_helpers() -> None:
    assert _release_tuple("3.0.107") == (3, 0, 107)
    assert _release_tuple("nope") is None
    assert _pascal_case("CUSTOMER_RESPONSE") == "CustomerResponse"
    assert _pascal_case("---") == "Schema"
    assert _camel_case("CUSTOMER-ID") == "customerId"
    assert _camel_case("") == "field"


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda spec: spec["zosConnect"].update(feature="zosConnect-2.0"), "OpenAPI 3.0"),
        (lambda spec: spec["zosConnect"].update(release="3.0.50"), "too old"),
        (lambda spec: spec["zosConnect"].update(apiType="requester", release="3.0.98"), "3.0.99"),
        (lambda spec: spec["zosConnect"].update(apiType="requester", release="3.0.86"), "PATCH"),
        (lambda spec: spec["zosConnect"].update(feature="bad"), "feature"),
        (lambda spec: spec["zosConnect"].update(apiType="bad"), "apiType"),
        (lambda spec: spec["zosConnect"].update(contextRoot="/other"), "does not match"),
        (lambda spec: spec["zosConnect"].pop("release"), "release"),
    ],
)
def test_zos_connect_gates(mutate, expected: str) -> None:
    spec = load_valid_spec()
    spec["operation"]["method"] = "patch"
    mutate(spec)
    with pytest.raises(GenerationError) as error:
        build(spec)
    assert expected in " ".join(error.value.messages)


def test_zos_connect_invalid_object_and_patch_review() -> None:
    spec = load_valid_spec()
    spec["zosConnect"] = "bad"
    with pytest.raises(GenerationError, match="zosConnect must be an object"):
        build(spec)
    spec = load_valid_spec()
    spec["operation"]["method"] = "patch"
    result = build(spec)
    assert "PATCH support must be confirmed" in result.report


def test_requester_swagger_gate_passes_and_swagger2_provider() -> None:
    spec = load_valid_spec()
    spec["zosConnect"].update(apiType="requester", release="3.0.99")
    spec["format"] = "swagger2"
    result = build(spec)
    assert result.swagger["swagger"] == "2.0"
    spec = load_valid_spec()
    spec["format"] = "swagger2"
    spec["zosConnect"]["release"] = "3.0.100"
    assert build(spec).swagger["swagger"] == "2.0"


@pytest.mark.parametrize(
    "parameters,expected",
    [
        ("bad", "parameters must be a list"),
        ([1], "must be an object"),
        ([{"name": "", "in": ""}], "valid in value"),
        ([{"name": "x", "in": "cookie"}], "Cookie parameter"),
        ([{"name": "x", "in": "query"}, {"name": "x", "in": "query"}], "Duplicate parameter"),
        ([{"name": "unknown", "in": "path"}], "does not appear"),
        ([{"name": "customerId", "in": "path", "type": "object"}], "unsupported type"),
        ([{"name": "customerId", "in": "path", "type": "integer", "format": "uuid"}], "unsupported format"),
    ],
)
def test_parameter_errors(parameters, expected: str) -> None:
    spec = load_valid_spec()
    spec["parameters"] = parameters
    with pytest.raises(GenerationError) as error:
        build(spec)
    assert expected in " ".join(error.value.messages)


def test_missing_path_parameter_placeholder() -> None:
    spec = load_valid_spec()
    spec["parameters"] = []
    with pytest.raises(GenerationError, match="no path parameter"):
        build(spec)


def test_parameter_descriptions_examples_and_formats() -> None:
    spec = load_valid_spec()
    spec["parameters"] = [
        {"name": "customerId", "in": "path", "type": "integer", "format": "int64", "description": "ID", "example": 7},
        {"name": "verbose", "in": "query", "type": "boolean", "description": "Verbose"},
        {"name": "X-Trace", "in": "header", "type": "string"},
    ]
    result = build(spec)
    params = result.openapi["paths"]["/customers/{customerId}"]["put"]["parameters"]
    assert params[0]["schema"]["example"] == 7
    assert params[1]["required"] is False
    assert params[2]["in"] == "header"


def test_mapping_configuration_variants() -> None:
    spec = load_valid_spec()
    spec["mapping"] = {
        "naming": "preserve",
        "required": [{"field": "CUSTOMER-ID", "evidence": "contract"}, {"field": "CITY", "evidence": "contract"}],
        "exclude": ["CUSTOMER-COUNT", {"field": "STREET", "reason": "PII"}],
        "redefines": [{"field": "BANK-DATA", "decision": "use-first-view"}],
        "odo": [{"field": "ITEM-COUNT", "expose": True}],
        "enums": [{"field": "CUSTOMER-TYPE", "values": ["I"]}],
        "fieldOverrides": {
            "CUSTOMER-NAME": {"type": "string", "maxLength": 50, "description": "Name", "example": "Ada", "enum": ["Ada", "Bob"]}
        },
        "examples": [{"field": "CUSTOMER-ID", "value": 1}, {"field": "no-value"}],
    }
    result = build(spec)
    request = result.swagger["definitions"]["UpdateCustomerRequest"]
    assert "CUSTOMER-NAME" in request["properties"]
    assert request["properties"]["CUSTOMER-NAME"]["maxLength"] == 50
    assert request["properties"]["CUSTOMER-ID"]["example"] == 1
    assert "CUSTOMER-COUNT" not in request["properties"]
    assert "STREET" not in request["properties"]["CUSTOMER-ADDRESS"]["items"]["properties"]
    assert "customerId" not in request["properties"]


def test_mapping_invalid_shapes() -> None:
    spec = load_valid_spec()
    spec["mapping"] = {
        "naming": "snake_case",
        "required": [{"field": "A"}, {"field": "B", "evidence": "ok"}],
        "exclude": [{"field": "C", "reason": "ok"}, {"reason": "bad"}],
        "redefines": [{"field": "D", "decision": "use-first-view"}],
        "odo": [{"field": "E"}],
        "enums": [{"field": "F", "values": ["x"]}, {"field": "G", "values": []}],
        "fieldOverrides": [{"field": "CUSTOMER-NAME", "type": "unsupported"}, {"type": "string"}],
    }
    with pytest.raises(GenerationError) as error:
        build(spec)
    messages = " ".join(error.value.messages)
    assert "naming" in messages
    assert "Each required entry needs field and evidence" in messages
    assert "Each exclude entry needs field and reason" in messages
    assert "invalid-enum" not in messages
    assert "Each field override needs field" in messages
    assert "unsupported override type" in messages


def test_redefines_decisions(copybooks_dir: Path) -> None:
    source = copybooks_dir / "redefines.cbl"

    def make(decision: str | None) -> dict:
        spec = load_valid_spec()
        spec["request"]["copybook"] = str(source)
        spec["responses"] = [{"code": "200", "description": "ok"}]
        spec["mapping"] = {"naming": "camelCase"}
        if decision:
            spec["mapping"]["redefines"] = [{"field": "BANK-DATA", "decision": decision}]
        return spec

    ambiguous = build(make(None), copybook_paths=[copybooks_dir])
    assert "needs-review" in ambiguous.report
    first = build(make("use-first-view"), copybook_paths=[copybooks_dir])
    assert "bankData" not in first.swagger["definitions"]["UpdateCustomerRequest"]["properties"]
    second = build(make("use-redefine-view"), copybook_paths=[copybooks_dir])
    assert "cardData" not in second.swagger["definitions"]["UpdateCustomerRequest"]["properties"]
    assert "bankData" in second.swagger["definitions"]["UpdateCustomerRequest"]["properties"]
    excluded = build(make("exclude-all"), copybook_paths=[copybooks_dir])
    properties = excluded.swagger["definitions"]["UpdateCustomerRequest"]["properties"]
    assert "cardData" not in properties and "bankData" not in properties
    with pytest.raises(GenerationError, match="one-of"):
        build(make("one-of"), copybook_paths=[copybooks_dir])
    with pytest.raises(GenerationError, match="unknown decision"):
        build(make("invalid"), copybook_paths=[copybooks_dir])


def test_odo_missing_counter(tmp_path: Path) -> None:
    source = tmp_path / "odo.cbl"
    source.write_text(
        "       01  R.\n           05  ITEMS OCCURS 0 TO 2 DEPENDING ON COUNT.\n               10  X PIC X(1).\n",
        encoding="utf-8",
    )
    spec = load_valid_spec()
    spec["request"]["copybook"] = str(source)
    spec["responses"] = [{"code": "200", "description": "ok"}]
    with pytest.raises(GenerationError, match="not in the same parsed copybook"):
        build(spec, copybook_paths=[tmp_path])


def test_odo_exposed_counter(copybooks_dir: Path) -> None:
    spec = load_valid_spec()
    spec["mapping"]["odo"] = [{"field": "ITEM-COUNT", "expose": True}]
    result = build(spec, copybook_paths=[copybooks_dir])
    response = result.swagger["definitions"]["UpdateCustomer200Response"]
    assert "itemCount" in response["properties"]
    assert "ODO `ITEM-COUNT`: exposed" in result.report


def test_naming_and_fillers_and_duplicates(tmp_path: Path) -> None:
    source = tmp_path / "dupes.cbl"
    source.write_text(
        "       01  R.\n"
        "           05  FILLER PIC X(1).\n"
        "           05  CUSTOMER-ID PIC 9(2).\n"
        "           05  CUSTOMER-ID PIC 9(2).\n",
        encoding="utf-8",
    )
    spec = load_valid_spec()
    spec["request"]["copybook"] = str(source)
    spec["responses"] = [{"code": "200", "description": "ok"}]
    spec["mapping"]["naming"] = "preserve"
    with pytest.raises(GenerationError, match="Duplicate JSON property"):
        build(spec, copybook_paths=[tmp_path])


def test_schema_validation_errors(tmp_path: Path) -> None:
    spec = load_valid_spec()
    spec["responses"] = [{"code": "200", "description": "ok"}]
    spec["request"] = {}
    builder = ContractBuilder(spec)
    bad_schemas = [
        {"type": "array"},
        {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 1},
        {"type": "object", "properties": "bad"},
        {"type": "object", "properties": {"x": {"type": "string"}}, "required": "x"},
        {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["missing"]},
        {"type": "null"},
        {"type": "integer", "format": "uuid"},
        {"type": "boolean", "format": "x"},
        {"type": "string", "maxLength": 1},
        {"type": "object", "properties": {"x": {"oneOf": [{"type": "string"}]}}},
        {"allOf": [{"type": "string"}], "properties": {}},
        {"$ref": "https://example.com/schema.json"},
        {"nullable": True},
        {"type": "string", "maxLength": 3},
    ]
    for schema in bad_schemas:
        builder._validate_schema(schema, "test", as_property=True)
    text = " ".join(item.message for item in builder.diagnostics)
    assert "without items" in text
    assert "minItems > maxItems" in text
    assert "must be an object" in text
    assert "must be a list" in text
    assert "missing property" in text
    assert "unsupported type" in text
    assert "unsupported format" in text
    assert "boolean" in text
    assert "composite" in text
    assert "non-local reference" in text
    assert "nullable without a type" in text


def test_override_type_clears_previous_schema(copybooks_dir: Path) -> None:
    spec = load_valid_spec()
    spec["mapping"]["fieldOverrides"] = [
        {"field": "ACCOUNT-BALANCE", "type": "string", "format": "decimal", "maxLength": 20, "description": "Text balance"},
        {"field": "CUSTOMER-NAME", "type": "object"},
    ]
    result = build(spec, copybook_paths=[copybooks_dir])
    balance = result.swagger["definitions"]["UpdateCustomer200Response"]["properties"]["accountBalance"]
    assert balance["type"] == "string"
    assert balance["format"] == "decimal"
    assert balance["description"] == "Text balance"


def test_no_request_and_no_schemas() -> None:
    spec = load_valid_spec()
    spec.pop("request")
    spec["responses"] = [{"code": "204", "description": "No content"}]
    result = build(spec)
    assert "requestBody" not in result.openapi["paths"]["/customers/{customerId}"]["put"]
    assert result.swagger["definitions"] == {}


def test_cli_success_json_and_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = write_spec(tmp_path, load_valid_spec())
    args = ["--spec", str(source), "--out", str(tmp_path / "out"), "--copybook-path", str(ROOT / "tests/fixtures/copybooks")]
    assert generate_contract.main(args + ["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert "swagger" in payload["outputs"]
    assert generate_contract.main(args) == 0
    assert "Generated:" in capsys.readouterr().out
    assert generate_contract.main(["--spec", str(tmp_path / "missing.json")]) == 1
    assert "error:" in capsys.readouterr().err


def test_generate_spec_without_output_uses_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    spec = load_valid_spec()
    spec.pop("output")
    for key in ("request",):
        spec[key]["copybook"] = str(ROOT / spec[key]["copybook"])
    for response in spec["responses"]:
        if response.get("copybook"):
            response["copybook"] = str(ROOT / response["copybook"])
    result = generate(write_spec(tmp_path, spec), copybook_paths=[ROOT / "tests/fixtures/copybooks"])
    assert result.output_paths["swagger"] == Path("zosconnect-contract/swagger.json")


def test_invalid_api_operation_shapes(tmp_path: Path) -> None:
    spec = load_valid_spec()
    spec["api"] = "bad"
    spec["operation"] = "bad"
    with pytest.raises(GenerationError) as error:
        build(spec)
    messages = " ".join(error.value.messages)
    assert "api must be an object" in messages
    assert "operation must be an object" in messages
