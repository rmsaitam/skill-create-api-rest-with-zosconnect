from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/cobol-openapi-generator/scripts"
sys.path.insert(0, str(SCRIPTS))

import generate_contract  # noqa: E402
import validate_contract  # noqa: E402
from validate_contract import (  # noqa: E402
    Report,
    _resolve_pointer,
    compare_contracts,
    load_document,
    parse_mapping,
    validate_contract as run_validation,
    validate_mapping_coverage,
    validate_mapping_rows,
    validate_openapi,
    validate_swagger,
)


def valid_swagger() -> dict:
    return {
        "swagger": "2.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "basePath": "/api",
        "paths": {
            "/things/{id}": {
                "get": {
                    "operationId": "getThing",
                    "summary": "Get thing",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "type": "integer", "format": "int64"}
                    ],
                    "responses": {"200": {"description": "OK", "schema": {"$ref": "#/definitions/Thing"}}},
                }
            }
        },
        "definitions": {
            "Thing": {
                "type": "object",
                "properties": {"id": {"type": "integer", "format": "int64"}, "name": {"type": "string"}},
                "required": ["id"],
            }
        },
    }


def valid_openapi() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Test API", "version": "1.0.0"},
        "servers": [{"url": "https://example.com/api"}],
        "paths": {
            "/things/{id}": {
                "get": {
                    "operationId": "getThing",
                    "summary": "Get thing",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer", "format": "int64"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}},
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Thing": {
                    "type": "object",
                    "properties": {"id": {"type": "integer", "format": "int64"}, "name": {"type": "string"}},
                    "required": ["id"],
                }
            }
        },
    }


def write_json(tmp_path: Path, name: str, data: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def write_text(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def errors(report: Report) -> str:
    return " ".join(f"{item.code}: {item.message}" for item in report.errors)


@pytest.fixture
def generated(tmp_path: Path) -> tuple[Path, Path, Path]:
    spec = json.loads((ROOT / "tests/fixtures/contracts/valid-spec.json").read_text(encoding="utf-8"))
    result = generate_contract.generate(
        write_json(tmp_path, "spec.json", spec),
        out_dir=tmp_path / "out",
        copybook_paths=[ROOT / "tests/fixtures/copybooks"],
    )
    return result.output_paths["swagger"], result.output_paths["openapi"], result.output_paths["mapping"]


def test_generated_contracts_are_valid(generated: tuple[Path, Path, Path]) -> None:
    swagger, openapi, mapping = generated
    report = run_validation(
        swagger_path=swagger,
        openapi_path=openapi,
        mapping_path=mapping,
        copybooks=[
            ROOT / "tests/fixtures/copybooks/customer-request.cbl",
            ROOT / "tests/fixtures/copybooks/customer-response.cbl",
            ROOT / "tests/fixtures/copybooks/error-response.cbl",
        ],
        context_root="/api/customer",
    )
    assert report.ok, errors(report)
    assert report.stats["copybooks"] == 3


def test_validate_minimal_documents() -> None:
    report = Report()
    validate_swagger(valid_swagger(), report, "/api")
    validate_openapi(valid_openapi(), report, "/api")
    assert report.ok, errors(report)
    assert not report.warnings


def test_missing_files_and_documents(tmp_path: Path) -> None:
    report = run_validation(swagger_path=tmp_path / "missing.json", mapping_path=tmp_path / "missing.md")
    assert not report.ok
    assert {item.code for item in report.errors} >= {"missing-file"}


def test_load_invalid_json_yaml_and_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = Report()
    assert load_document(write_text(tmp_path, "bad.json", "{"), report) is None
    assert load_document(write_text(tmp_path, "array.json", "[]"), report) is None
    assert load_document(write_text(tmp_path, "bad.yaml", "a: [\n"), report) is None
    assert load_document(write_text(tmp_path, "empty.yaml", ""), report) is None
    assert {item.code for item in report.errors} >= {"invalid-json", "invalid-document-root", "invalid-yaml"}
    monkeypatch.setattr(validate_contract, "yaml", None)
    assert load_document(write_text(tmp_path, "doc.yaml", "openapi: 3.0.3\n"), report) is None
    assert any(item.code == "missing-pyyaml" for item in report.errors)


def test_swagger_structure_errors() -> None:
    document = {"swagger": "3.0", "paths": {}}
    report = Report()
    validate_swagger(document, report)
    codes = {item.code for item in report.errors}
    assert "invalid-swagger-version" in codes
    assert "missing-info" in codes
    assert "missing-paths" in codes
    document = {"swagger": "2.0", "info": {"title": "", "version": ""}, "basePath": "bad", "paths": {"/": {"get": []}}}
    validate_swagger(document, report)
    assert "missing-info-field" in {item.code for item in report.errors}
    assert "invalid-base-path" in {item.code for item in report.errors}


def test_openapi_structure_errors() -> None:
    report = Report()
    validate_openapi({"openapi": "3.1.0"}, report)
    assert "invalid-openapi-version" in {item.code for item in report.errors}
    assert "missing-info" in {item.code for item in report.errors}
    assert "missing-servers" in {item.code for item in report.errors}
    assert "missing-paths" in {item.code for item in report.errors}
    document = valid_openapi()
    document["servers"] = [{"url": "example.com/api"}]
    validate_openapi(document, report)
    assert "invalid-server" in {item.code for item in report.errors}
    document = valid_openapi()
    document["servers"] = [{}]
    validate_openapi(document, report)
    assert "invalid-server" in {item.code for item in report.errors}
    document = valid_openapi()
    document["servers"] = [{"url": "https://example.com"}]
    report = Report()
    validate_openapi(document, report, "/")
    assert report.ok, errors(report)


def test_context_root_mismatch_and_invalid_base_path() -> None:
    report = Report()
    validate_swagger(valid_swagger(), report, "/other")
    validate_openapi(valid_openapi(), report, "/other")
    assert {item.code for item in report.errors} == {"context-root-mismatch"}
    document = valid_swagger()
    document["basePath"] = 5
    report = Report()
    validate_swagger(document, report)
    assert any(item.code == "invalid-base-path" for item in report.errors)


def test_swagger_path_and_operation_errors() -> None:
    document = valid_swagger()
    document["paths"] = {
        "bad": {},
        "/bad-item": [],
        "/dup": {
            "get": {
                "operationId": "getThing",
                "summary": "Duplicate",
                "responses": {"200": {"description": "ok"}},
            }
        },
        "/x": {
            "head": {},
            "trace": {},
            "options": {
                "operationId": "getThing",
                "summary": "",
                "parameters": "bad",
                "responses": {},
            },
        },
    }
    report = Report()
    validate_swagger(document, report)
    codes = {item.code for item in report.errors}
    assert {"invalid-path", "invalid-path-item", "unsupported-method", "missing-summary", "invalid-parameters"} <= codes
    assert "duplicate-operation-id" in codes
    assert "missing-responses" in codes


def test_operation_errors() -> None:
    document = valid_swagger()
    operation = document["paths"]["/things/{id}"]["get"]
    operation["operationId"] = ""
    operation["summary"] = ""
    operation["parameters"] = [{"name": "id", "in": "body"}]
    report = Report()
    validate_swagger(document, report)
    codes = {item.code for item in report.errors}
    assert "missing-operation-id" in codes
    assert "missing-summary" in codes
    assert "missing-body-schema" in codes
    document = valid_swagger()
    document["paths"]["/things/{id}"]["get"] = "bad"
    report = Report()
    validate_swagger(document, report)
    assert "invalid-operation" in {item.code for item in report.errors}


def test_parameter_validation_errors() -> None:
    document = valid_swagger()
    document["paths"]["/things/{id}"]["get"]["parameters"] = [
        "bad",
        {"name": "", "in": "query"},
        {"name": "x", "in": "bad"},
        {"name": "cookie", "in": "cookie"},
        {"name": "x", "in": "query"},
        {"name": "x", "in": "query"},
        {"name": "body", "in": "body", "schema": {"type": "string"}},
        {"name": "unknown", "in": "path"},
    ]
    report = Report()
    validate_swagger(document, report)
    codes = {item.code for item in report.errors}
    assert {
        "invalid-parameter",
        "invalid-parameter-name",
        "invalid-parameter-location",
        "unsupported-parameter-location",
        "duplicate-parameter",
        "unsupported-parameter-location",
        "missing-path-parameter",
    } <= codes
    document = valid_openapi()
    document["paths"]["/things/{id}"]["get"]["parameters"] = [
        {"name": "id", "in": "body", "schema": {"type": "string"}},
        {"name": "x", "in": "query"},
    ]
    report = Report()
    validate_openapi(document, report)
    assert "invalid-body-parameter" in {item.code for item in report.errors}
    assert "missing-parameter-schema" in {item.code for item in report.errors}


def test_response_errors() -> None:
    document = valid_swagger()
    operation = document["paths"]["/things/{id}"]["get"]
    operation["responses"] = {
        "2XX": {"description": "Range"},
        200: {"description": ""},
        "bad": [],
        "404": {"schema": {"type": "string"}},
    }
    report = Report()
    validate_swagger(document, report)
    codes = {item.code for item in report.errors}
    assert "response-range" in codes
    assert "unquoted-response-code" in codes
    assert "invalid-response-code" in codes
    assert "missing-response-description" in codes
    assert "invalid-response" in codes
    operation["responses"] = {"200": {"description": "ok", "schema": {}}}
    report = Report()
    validate_swagger(document, report)
    assert "unsupported-type" not in {item.code for item in report.errors}


def test_openapi_request_and_response_content_errors() -> None:
    document = valid_openapi()
    operation = document["paths"]["/things/{id}"]["get"]
    operation["requestBody"] = "bad"
    operation["responses"] = {
        "200": {"description": "ok", "content": "bad"},
        "201": {"description": "ok", "content": {"application/json": {}}},
    }
    report = Report()
    validate_openapi(document, report)
    codes = {item.code for item in report.errors}
    assert {"invalid-request-body", "invalid-content", "missing-media-schema"} <= codes
    operation["requestBody"] = {"content": {}}
    report = Report()
    validate_openapi(document, report)
    assert "missing-request-content" in {item.code for item in report.errors}
    operation["requestBody"] = {"content": {"application/json": {}}}
    report = Report()
    validate_openapi(document, report)
    assert "missing-request-schema" in {item.code for item in report.errors}


def test_schema_errors_and_warnings() -> None:
    document = valid_swagger()
    document["definitions"] = {
        "Bad": {
            "type": "object",
            "properties": {
                "array": {"type": "array"},
                "limits": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 1},
                "composite": {"oneOf": [{"type": "string"}]},
                "required": {"type": "object", "properties": "bad", "required": "x"},
                "missing": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["y"]},
                "badFormat": {"type": "integer", "format": "uuid"},
                "boolFormat": {"type": "boolean", "format": "x"},
                "maxLength": {"type": "integer", "maxLength": 2},
                "nullable": {"nullable": True},
                "null": {"type": "null"},
                "external": {"$ref": "https://example.com/schema.json"},
                "missingType": {},
            },
        }
    }
    report = Report()
    validate_swagger(document, report)
    codes = {item.code for item in report.errors}
    assert {
        "array-without-items",
        "invalid-array-limit",
        "unsupported-composite",
        "invalid-properties",
        "invalid-required",
        "required-not-in-properties",
        "unsupported-format",
        "boolean-format",
        "nullable-without-type",
        "null-type",
        "external-reference",
    } <= codes
    assert "maxlength-on-non-string" in {item.code for item in report.warnings}
    assert "missing-type" in {item.code for item in report.warnings}


def test_unresolved_and_escaped_references() -> None:
    document = valid_swagger()
    document["definitions"]["Thing"]["properties"]["other"] = {"$ref": "#/definitions/Missing"}
    report = Report()
    validate_swagger(document, report)
    assert "unresolved-reference" in {item.code for item in report.errors}
    pointer_document = {"a/b": {"~key": [{"value": 1}]}}
    assert _resolve_pointer(pointer_document, "#/a~1b/~0key/0/value") == 1
    with pytest.raises(KeyError):
        _resolve_pointer(pointer_document, "#/missing")


def test_component_schema_shapes() -> None:
    report = Report()
    validate_swagger({"swagger": "2.0", "info": {"title": "T", "version": "1"}, "paths": {"/x": {"get": {"operationId": "x", "summary": "s", "responses": {"200": {"description": "ok"}}}}}, "definitions": "bad"}, report)
    assert "invalid-schemas" in {item.code for item in report.errors}
    report = Report()
    validate_openapi({"openapi": "3.0.3", "info": {"title": "T", "version": "1"}, "servers": [{"url": "/api"}], "paths": {"/x": {"get": {"operationId": "x", "summary": "s", "responses": {"200": {"description": "ok"}}}}}, "components": "bad"}, report)
    assert "invalid-components" in {item.code for item in report.errors}


def test_compare_contracts_detects_drift() -> None:
    report = Report()
    compare_contracts(valid_swagger(), valid_openapi(), report)
    assert report.ok
    openapi = valid_openapi()
    openapi["paths"]["/other"] = openapi["paths"].pop("/things/{id}")
    report = Report()
    compare_contracts(valid_swagger(), openapi, report)
    assert "cross-format-paths" in {item.code for item in report.errors}
    openapi = valid_openapi()
    openapi["components"]["schemas"]["Other"] = openapi["components"]["schemas"].pop("Thing")
    report = Report()
    compare_contracts(valid_swagger(), openapi, report)
    assert "cross-format-schemas" in {item.code for item in report.errors}
    openapi = valid_openapi()
    operation = openapi["paths"]["/things/{id}"]["get"]
    operation["operationId"] = "other"
    operation["responses"]["201"] = {"description": "created"}
    operation["parameters"] = [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}]
    report = Report()
    compare_contracts(valid_swagger(), openapi, report)
    codes = {item.code for item in report.errors}
    assert {"cross-format-operation-ids", "cross-format-responses"} <= codes


def test_mapping_validation() -> None:
    text = """
| COBOL field | JSON path | JSON type | Required | Evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| A | a | string | yes | contract | mapped | |
| B | b | string | no | - | excluded | |
| C | c | string | maybe | - | unknown | |
| D | d | string | no | - | mapped | |
|  | e | string | no | - | mapped | |
"""
    report = Report()
    rows = parse_mapping(text, report)
    validate_mapping_rows(rows, report)
    codes = {item.code for item in report.errors}
    assert "missing-required-evidence" not in codes
    assert "missing-exclusion-reason" in codes
    assert "invalid-required-flag" in codes
    assert "invalid-mapping-status" in codes
    assert "missing-mapping-field" in codes


def test_mapping_required_without_evidence() -> None:
    text = """
| COBOL field | JSON path | JSON type | Required | Evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| A | a | string | yes | - | mapped | |
"""
    report = Report()
    validate_mapping_rows(parse_mapping(text, report), report)
    assert "missing-required-evidence" in {item.code for item in report.errors}


def test_mapping_table_shape_errors(tmp_path: Path) -> None:
    report = Report()
    assert parse_mapping("no table", report) == []
    assert "missing-mapping-table" in {item.code for item in report.errors}
    report = Report()
    parse_mapping("| X | Y | Z | W | V | U |\n| --- | --- | --- | --- | --- | --- |\n| a | b | c | d | e | f |", report)
    assert "missing-mapping-column" in {item.code for item in report.errors}
    report = Report()
    parse_mapping("| COBOL field | JSON path | JSON type | Required | Evidence | Status |\n| --- | --- | --- | --- | --- | --- |\n| x |", report)
    assert "invalid-mapping-row" in {item.code for item in report.errors}


def test_mapping_coverage(tmp_path: Path) -> None:
    copybook = write_text(
        tmp_path,
        "map.cbl",
        "       01  R.\n           05  A PIC X(1).\n           05  B REDEFINES A PIC X(1).\n",
    )
    report = Report()
    validate_mapping_coverage([], [copybook], report)
    assert "field-not-in-mapping" in {item.code for item in report.errors}
    report = Report()
    rows = [
        {"cobol field": "R", "status": "mapped"},
        {"cobol field": "A", "status": "mapped"},
        {"cobol field": "B", "status": "mapped"},
    ]
    validate_mapping_coverage(rows, [copybook], report)
    assert "unreviewed-redefines" in {item.code for item in report.warnings}
    broken = write_text(tmp_path, "broken.cbl", "")
    report = Report()
    validate_mapping_coverage([], [broken], report)
    assert "empty-copybook" in {item.code for item in report.errors}


def test_validate_contract_missing_mapping_warning(tmp_path: Path) -> None:
    swagger = write_json(tmp_path, "swagger.json", valid_swagger())
    report = run_validation(swagger_path=swagger, copybooks=[ROOT / "tests/fixtures/copybooks/customer-request.cbl"])
    assert "missing-mapping" in {item.code for item in report.warnings}


def test_cli_modes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        validate_contract.main([])
    swagger = write_json(tmp_path, "swagger.json", valid_swagger())
    assert validate_contract.main(["--swagger", str(swagger), "--context-root", "/api"]) == 0
    assert "PASS" in capsys.readouterr().out
    assert validate_contract.main(["--swagger", str(swagger), "--context-root", "/api", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert validate_contract.main(["--swagger", str(swagger), "--context-root", "/other"]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert validate_contract.main([
        "--swagger",
        str(swagger),
        "--copybook",
        str(ROOT / "tests/fixtures/copybooks/customer-request.cbl"),
        "--strict",
    ]) == 1
