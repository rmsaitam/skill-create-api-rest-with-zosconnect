#!/usr/bin/env python3
"""Validate Swagger 2.0, OpenAPI 3.0, and copybook mapping artifacts.

The validator is intentionally self-contained: it checks syntax, local
references, cross-format consistency, the documented z/OS Connect restrictions,
and the mapping table required by the skill. It never modifies an artifact.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent
    yaml = None  # type: ignore[assignment]

from copybook_parser import CopybookParser, ParsedCopybook

ALLOWED_METHODS = {"get", "put", "post", "delete", "options", "patch"}
HTTP_METHOD_KEYS = ALLOWED_METHODS | {"head", "trace"}
RESPONSE_CODE_RE = re.compile(r"^(?:default|[1-5]\d{2})$")
RESPONSE_RANGE_RE = re.compile(r"^[1-5]XX$", re.IGNORECASE)
PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")
SUPPORTED_TYPES = {"string", "integer", "number", "boolean", "object", "array"}
FORMAT_RULES: dict[str, set[str] | None] = {
    "integer": {"int32", "int64"},
    "number": {"float", "double", "decimal"},
    "boolean": set(),
    "string": None,
}
VALID_STATUSES = {"mapped", "excluded", "needs-review"}
MAPPING_COLUMNS = (
    "cobol field",
    "json path",
    "json type",
    "required",
    "evidence",
    "status",
)


@dataclass
class Issue:
    level: str
    code: str
    message: str
    location: str = ""


@dataclass
class Report:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    info: list[Issue] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)

    def error(self, code: str, message: str, location: str = "") -> None:
        self.errors.append(Issue("error", code, message, location))

    def warning(self, code: str, message: str, location: str = "") -> None:
        self.warnings.append(Issue("warning", code, message, location))

    def note(self, code: str, message: str, location: str = "") -> None:
        self.info.append(Issue("info", code, message, location))

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "pass" if self.ok else "fail",
            "stats": self.stats,
            "errors": [issue.__dict__ for issue in self.errors],
            "warnings": [issue.__dict__ for issue in self.warnings],
            "info": [issue.__dict__ for issue in self.info],
        }


def _read_text(path: Path, report: Report) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        report.error("missing-file", f"File not found: {path}", str(path))
    except OSError as error:
        report.error("unreadable-file", f"Cannot read {path}: {error}", str(path))
    return ""


def load_document(path: str | Path, report: Report) -> dict[str, Any] | None:
    file_path = Path(path)
    text = _read_text(file_path, report)
    if not text:
        return None
    suffix = file_path.suffix.lower()
    data: Any
    try:
        if suffix == ".json":
            data = json.loads(text)
        else:
            if yaml is None:
                report.error("missing-pyyaml", f"PyYAML is required to read {file_path}.")
                return None
            data = yaml.safe_load(text)
    except json.JSONDecodeError as error:
        report.error("invalid-json", f"Invalid JSON in {file_path}: {error}", str(file_path))
        return None
    except yaml.YAMLError as error:  # type: ignore[union-attr]
        report.error("invalid-yaml", f"Invalid YAML in {file_path}: {error}", str(file_path))
        return None
    if not isinstance(data, dict):
        report.error("invalid-document-root", f"{file_path} must contain an object.", str(file_path))
        return None
    return data


def _resolve_pointer(document: dict[str, Any], pointer: str) -> Any:
    current: Any = document
    for raw in pointer.lstrip("#/").split("/"):
        token = unquote(raw).replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise KeyError(pointer)
    return current


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _collect_refs(document: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for value in _walk(document):
        if isinstance(value, dict) and isinstance(value.get("$ref"), str):
            refs.append((str(value["$ref"]), ""))
    return refs


def validate_refs(document: dict[str, Any], location: str, report: Report) -> None:
    for ref, _ in _collect_refs(document):
        if not ref.startswith("#/"):
            report.error("external-reference", f"{location} uses a non-local reference {ref!r}.", location)
            continue
        try:
            _resolve_pointer(document, ref)
        except KeyError:
            report.error("unresolved-reference", f"{location} contains an unresolved reference {ref!r}.", location)


def _validate_parameter(
    parameter: Any,
    location: str,
    path: str,
    report: Report,
    swagger: bool,
) -> tuple[str, str, bool] | None:
    if not isinstance(parameter, dict):
        report.error("invalid-parameter", f"{location} must be an object.", location)
        return None
    name = parameter.get("name")
    place = parameter.get("in")
    if not isinstance(name, str) or not name:
        report.error("invalid-parameter-name", f"{location} needs a name.", location)
        return None
    if place not in {"path", "query", "header", "cookie", "body", "formData"}:
        report.error("invalid-parameter-location", f"{location} has invalid in {place!r}.", location)
        return None
    if place == "cookie":
        report.error("unsupported-parameter-location", f"{location} uses cookie parameters, which z/OS Connect does not support.", location)
    required = bool(parameter.get("required", False))
    if place == "path":
        required = True
        if name not in PATH_PARAM_RE.findall(path):
            report.error("path-parameter-missing", f"{location} {name!r} is not present in {path}.", location)
    if place == "body":
        if not swagger:
            report.error("invalid-body-parameter", f"{location} uses in: body, which is Swagger 2.0 only.", location)
        schema = parameter.get("schema")
        if not isinstance(schema, dict):
            report.error("missing-body-schema", f"{location} body parameter needs a schema.", location)
        else:
            _validate_schema(schema, f"{location}.schema", report, as_property=False)
        return name, place, required
    schema = parameter.get("schema")
    if swagger:
        schema = {
            "type": parameter.get("type", "string"),
            **({"format": parameter["format"]} if parameter.get("format") else {}),
        }
    if not isinstance(schema, dict):
        report.error("missing-parameter-schema", f"{location} needs a schema.", location)
        return name, place, required
    _validate_schema(schema, f"{location}.schema", report, as_property=False)
    return name, place, required


def _validate_parameters(
    parameters: Any,
    path: str,
    location: str,
    report: Report,
    swagger: bool,
) -> None:
    if parameters is None:
        return
    if not isinstance(parameters, list):
        report.error("invalid-parameters", f"{location} must be a list.", location)
        return
    seen: set[tuple[str, str]] = set()
    path_names: set[str] = set()
    for index, parameter in enumerate(parameters):
        result = _validate_parameter(parameter, f"{location}[{index}]", path, report, swagger)
        if result is None:
            continue
        name, place, _required = result
        key = (name, place)
        if key in seen:
            report.error("duplicate-parameter", f"{location} repeats parameter {name!r} in {place!r}.", location)
        seen.add(key)
        if place == "path":
            path_names.add(name)
    missing = set(PATH_PARAM_RE.findall(path)) - path_names
    for name in sorted(missing):
        report.error("missing-path-parameter", f"{location} does not declare path parameter {name!r}.", location)


def _validate_responses(responses: Any, location: str, report: Report, swagger: bool) -> set[str]:
    if not isinstance(responses, dict) or not responses:
        report.error("missing-responses", f"{location} needs at least one response.", location)
        return set()
    codes: set[str] = set()
    for raw_code, response in responses.items():
        code = str(raw_code)
        if not isinstance(raw_code, str):
            report.error(
                "unquoted-response-code",
                f"{location} response code {raw_code!r} must be a quoted string.",
                location,
            )
        if RESPONSE_RANGE_RE.match(code):
            report.error("response-range", f"{location} uses unsupported response range {code!r}.", location)
        elif not RESPONSE_CODE_RE.match(code):
            report.error("invalid-response-code", f"{location} has invalid response code {code!r}.", location)
        if not isinstance(response, dict):
            report.error("invalid-response", f"{location}.{code} must be an object.", location)
            continue
        if not str(response.get("description", "")).strip():
            report.error("missing-response-description", f"{location}.{code} needs a description.", location)
        if swagger:
            schema = response.get("schema")
            if schema is not None:
                _validate_schema(schema, f"{location}.{code}.schema", report, as_property=False)
        else:
            content = response.get("content")
            if content is not None:
                if not isinstance(content, dict):
                    report.error("invalid-content", f"{location}.{code}.content must be an object.", location)
                else:
                    for media_type, media in content.items():
                        if not isinstance(media, dict) or not isinstance(media.get("schema"), dict):
                            report.error(
                                "missing-media-schema",
                                f"{location}.{code}.content.{media_type} needs a schema.",
                                location,
                            )
                        else:
                            _validate_schema(
                                media["schema"],
                                f"{location}.{code}.content.{media_type}.schema",
                                report,
                                as_property=False,
                            )
        codes.add(code)
    if not any(code.startswith("2") for code in codes):
        report.error("missing-success-response", f"{location} needs at least one 2xx response.", location)
    return codes


def _validate_operation(
    path: str,
    method: str,
    operation: Any,
    location: str,
    report: Report,
    swagger: bool,
    operation_ids: dict[str, str],
) -> tuple[set[str], set[tuple[str, str]]]:
    if method not in ALLOWED_METHODS:
        report.error("unsupported-method", f"{location} uses unsupported method {method!r}.", location)
        return set(), set()
    if not isinstance(operation, dict):
        report.error("invalid-operation", f"{location} must be an object.", location)
        return set(), set()
    operation_id = operation.get("operationId")
    if not isinstance(operation_id, str) or not operation_id.strip():
        report.error("missing-operation-id", f"{location} needs operationId.", location)
    elif operation_id in operation_ids:
        report.error(
            "duplicate-operation-id",
            f"{location} repeats operationId {operation_id!r} from {operation_ids[operation_id]}.",
            location,
        )
    else:
        operation_ids[operation_id] = location
    if not str(operation.get("summary", "")).strip():
        report.error("missing-summary", f"{location} needs a summary.", location)
    _validate_parameters(operation.get("parameters"), path, f"{location}.parameters", report, swagger)
    if not swagger and operation.get("requestBody") is not None:
        request_body = operation["requestBody"]
        if not isinstance(request_body, dict):
            report.error("invalid-request-body", f"{location}.requestBody must be an object.", location)
        else:
            content = request_body.get("content")
            if not isinstance(content, dict) or not content:
                report.error("missing-request-content", f"{location}.requestBody needs content.", location)
            else:
                for media_type, media in content.items():
                    if not isinstance(media, dict) or not isinstance(media.get("schema"), dict):
                        report.error(
                            "missing-request-schema",
                            f"{location}.requestBody.content.{media_type} needs a schema.",
                            location,
                        )
                    else:
                        _validate_schema(
                            media["schema"],
                            f"{location}.requestBody.content.{media_type}.schema",
                            report,
                            as_property=False,
                        )
    codes = _validate_responses(operation.get("responses"), f"{location}.responses", report, swagger)
    parameter_keys = set()
    for parameter in operation.get("parameters") or []:
        if isinstance(parameter, dict) and isinstance(parameter.get("name"), str):
            parameter_keys.add((str(parameter["name"]), str(parameter.get("in", ""))))
    return codes, parameter_keys


def _validate_paths(
    document: dict[str, Any],
    location: str,
    report: Report,
    swagger: bool,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[tuple[str, str]]]]:
    paths = document.get("paths")
    if not isinstance(paths, dict) or not paths:
        report.error("missing-paths", f"{location} needs a non-empty paths object.", location)
        return {}, {}, {}
    methods_by_path: dict[str, set[str]] = {}
    codes_by_operation: dict[str, set[str]] = {}
    parameters_by_operation: dict[str, set[tuple[str, str]]] = {}
    operation_ids: dict[str, str] = {}
    for path, path_item in paths.items():
        if not isinstance(path, str) or not path.startswith("/"):
            report.error("invalid-path", f"{location} path {path!r} must start with '/'.", location)
            continue
        if not isinstance(path_item, dict):
            report.error("invalid-path-item", f"{location}.paths.{path} must be an object.", location)
            continue
        methods = {key.lower() for key in path_item if key.lower() in HTTP_METHOD_KEYS}
        methods_by_path[path] = methods
        _validate_parameters(path_item.get("parameters"), path, f"{location}.paths.{path}.parameters", report, swagger)
        for method in sorted(methods):
            op_location = f"{location}.paths.{path}.{method}"
            operation = path_item.get(method) or path_item.get(method.upper())
            if method in {"head", "trace"}:
                report.error("unsupported-method", f"{op_location} uses {method.upper()}, which z/OS Connect does not support.", op_location)
                continue
            codes, parameters = _validate_operation(path, method, operation, op_location, report, swagger, operation_ids)
            key = f"{path} {method}"
            codes_by_operation[key] = codes
            parameters_by_operation[key] = parameters
    return methods_by_path, codes_by_operation, parameters_by_operation


def _validate_schema(
    schema: Any,
    location: str,
    report: Report,
    as_property: bool = False,
) -> None:
    if not isinstance(schema, dict):
        report.error("invalid-schema", f"{location} must be an object.", location)
        return
    if "$ref" in schema:
        if not isinstance(schema["$ref"], str) or not schema["$ref"].startswith("#/"):
            report.error("external-reference", f"{location} uses a non-local reference {schema['$ref']!r}.", location)
        return
    composite = any(key in schema for key in ("allOf", "anyOf", "oneOf"))
    if composite and as_property:
        report.error(
            "unsupported-composite",
            f"{location} uses a composite type as a direct property; z/OS Connect does not support it.",
            location,
        )
    if composite and "properties" in schema:
        report.error("composite-with-properties", f"{location} combines a composite with properties.", location)
    if composite:
        return
    schema_type = schema.get("type")
    if schema_type is None:
        if not any(key in schema for key in ("properties", "items")):
            report.warning("missing-type", f"{location} has no type.", location)
    elif schema_type == "null" or schema_type is None:
        report.error("null-type", f"{location} uses type: null; OpenAPI 3.0 requires an explicit type.", location)
    elif schema_type not in SUPPORTED_TYPES:
        report.error("unsupported-type", f"{location} uses unsupported type {schema_type!r}.", location)
    if schema_type == "array":
        if not isinstance(schema.get("items"), dict):
            report.error("array-without-items", f"{location} is an array without items.", location)
        else:
            _validate_schema(schema["items"], f"{location}.items", report, as_property=True)
        for key in ("minItems", "maxItems"):
            if key in schema and not isinstance(schema[key], int):
                report.error("invalid-array-limit", f"{location}.{key} must be an integer.", location)
        if isinstance(schema.get("minItems"), int) and isinstance(schema.get("maxItems"), int):
            if schema["minItems"] > schema["maxItems"]:
                report.error("invalid-array-limit", f"{location} has minItems > maxItems.", location)
    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            report.error("invalid-properties", f"{location}.properties must be an object.", location)
        else:
            for name, child in properties.items():
                _validate_schema(child, f"{location}.properties.{name}", report, as_property=True)
        required = schema.get("required")
        if required is not None:
            if not isinstance(required, list):
                report.error("invalid-required", f"{location}.required must be a list.", location)
            else:
                for name in required:
                    if isinstance(properties, dict) and name not in properties:
                        report.error(
                            "required-not-in-properties",
                            f"{location}.required references missing property {name!r}.",
                            location,
                        )
    if schema_type in FORMAT_RULES and "format" in schema:
        fmt = str(schema["format"])
        allowed = FORMAT_RULES[schema_type]
        if schema_type == "boolean":
            report.error("boolean-format", f"{location} declares a format for a boolean.", location)
        elif allowed is not None and fmt not in allowed:
            report.error("unsupported-format", f"{location} uses unsupported format {fmt!r} for {schema_type}.", location)
    if "maxLength" in schema and schema_type != "string":
        report.warning("maxlength-on-non-string", f"{location} declares maxLength for a non-string type.", location)
    if "nullable" in schema and "type" not in schema:
        report.error("nullable-without-type", f"{location} uses nullable without an explicit type.", location)
    if "type" in schema and schema["type"] is None:
        report.error("null-type", f"{location} uses a null type.", location)


def _validate_component_schemas(document: dict[str, Any], location: str, report: Report, swagger: bool) -> set[str]:
    if swagger:
        schemas = document.get("definitions") or {}
        base = "definitions"
    else:
        components = document.get("components") or {}
        if not isinstance(components, dict):
            report.error("invalid-components", f"{location}.components must be an object.", location)
            components = {}
        schemas = components.get("schemas") or {}
        base = "components/schemas"
    if not isinstance(schemas, dict):
        report.error("invalid-schemas", f"{location}.{base} must be an object.", location)
        return set()
    for name, schema in schemas.items():
        _validate_schema(schema, f"{location}.{base}.{name}", report, as_property=False)
    return set(schemas)


def _validate_info(document: dict[str, Any], location: str, report: Report) -> None:
    info = document.get("info")
    if not isinstance(info, dict):
        report.error("missing-info", f"{location} needs an info object.", location)
        return
    for key in ("title", "version"):
        if not str(info.get(key, "")).strip():
            report.error("missing-info-field", f"{location}.info needs {key}.", location)


def _validate_context_root(
    document: dict[str, Any],
    location: str,
    report: Report,
    swagger: bool,
    context_root: str | None,
) -> None:
    if swagger:
        base_path = document.get("basePath")
        if base_path is not None and (not isinstance(base_path, str) or not base_path.startswith("/")):
            report.error("invalid-base-path", f"{location}.basePath must start with '/'.", location)
        actual = base_path
    else:
        servers = document.get("servers")
        if not isinstance(servers, list) or not servers:
            report.error("missing-servers", f"{location} needs a non-empty servers list.", location)
            return
        first = servers[0]
        if not isinstance(first, dict) or not isinstance(first.get("url"), str) or not first["url"]:
            report.error("invalid-server", f"{location}.servers[0] needs a URL.", location)
            return
        actual = first["url"]
        url = first["url"]
        if url.startswith(("http://", "https://")):
            after_scheme = url.split("://", 1)[1]
            actual = "/" + after_scheme.split("/", 1)[1] if "/" in after_scheme else "/"
        if not str(actual).startswith("/"):
            report.error("invalid-server", f"{location}.servers[0] URL needs a path.", location)
    if context_root and actual != context_root:
        report.error(
            "context-root-mismatch",
            f"{location} context root {actual!r} does not match {context_root!r}.",
            location,
        )


def validate_swagger(document: dict[str, Any], report: Report, context_root: str | None = None) -> None:
    if document.get("swagger") != "2.0":
        report.error("invalid-swagger-version", "Swagger document must declare swagger: '2.0'.", "swagger")
    _validate_info(document, "swagger", report)
    _validate_context_root(document, "swagger", report, True, context_root)
    _validate_paths(document, "swagger", report, True)
    _validate_component_schemas(document, "swagger", report, True)
    validate_refs(document, "swagger", report)


def validate_openapi(document: dict[str, Any], report: Report, context_root: str | None = None) -> None:
    version = str(document.get("openapi", ""))
    if not version.startswith("3.0."):
        report.error("invalid-openapi-version", f"OpenAPI version must be 3.0.x; got {version!r}.", "openapi")
    _validate_info(document, "openapi", report)
    _validate_context_root(document, "openapi", report, False, context_root)
    _validate_paths(document, "openapi", report, False)
    _validate_component_schemas(document, "openapi", report, False)
    validate_refs(document, "openapi", report)


def _path_method_map(document: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    paths = document.get("paths") or {}
    if isinstance(paths, dict):
        for path, item in paths.items():
            if isinstance(item, dict):
                result[str(path)] = {str(key).lower() for key in item if str(key).lower() in HTTP_METHOD_KEYS}
    return result


def _operation_ids(document: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    paths = document.get("paths") or {}
    if isinstance(paths, dict):
        for item in paths.values():
            if not isinstance(item, dict):
                continue
            for method, operation in item.items():
                if str(method).lower() in ALLOWED_METHODS and isinstance(operation, dict):
                    if isinstance(operation.get("operationId"), str):
                        result.add(operation["operationId"])
    return result


def _response_codes(document: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    paths = document.get("paths") or {}
    if isinstance(paths, dict):
        for path, item in paths.items():
            if not isinstance(item, dict):
                continue
            for method, operation in item.items():
                if str(method).lower() in ALLOWED_METHODS and isinstance(operation, dict):
                    responses = operation.get("responses")
                    if isinstance(responses, dict):
                        result[f"{path} {str(method).lower()}"] = {str(code) for code in responses}
    return result


def _schema_names(document: dict[str, Any], swagger: bool) -> set[str]:
    if swagger:
        definitions = document.get("definitions") or {}
        return set(definitions) if isinstance(definitions, dict) else set()
    components = document.get("components") or {}
    schemas = components.get("schemas") if isinstance(components, dict) else None
    return set(schemas) if isinstance(schemas, dict) else set()


def _required_by_schema(document: dict[str, Any], swagger: bool) -> dict[str, set[str]]:
    if swagger:
        schemas = document.get("definitions") or {}
    else:
        components = document.get("components") or {}
        schemas = components.get("schemas") if isinstance(components, dict) else {}
    result: dict[str, set[str]] = {}
    if isinstance(schemas, dict):
        for name, schema in schemas.items():
            if isinstance(schema, dict) and isinstance(schema.get("required"), list):
                result[str(name)] = {str(item) for item in schema["required"]}
    return result


def compare_contracts(swagger: dict[str, Any], openapi: dict[str, Any], report: Report) -> None:
    swagger_methods = _path_method_map(swagger)
    openapi_methods = _path_method_map(openapi)
    if set(swagger_methods) != set(openapi_methods):
        report.error("cross-format-paths", "Swagger and OpenAPI documents have different paths.")
    for path in sorted(set(swagger_methods) & set(openapi_methods)):
        if swagger_methods[path] != openapi_methods[path]:
            report.error("cross-format-methods", f"Swagger and OpenAPI differ on methods for {path}.")
    if _operation_ids(swagger) != _operation_ids(openapi):
        report.error("cross-format-operation-ids", "Swagger and OpenAPI documents have different operationId values.")
    if _response_codes(swagger) != _response_codes(openapi):
        report.error("cross-format-responses", "Swagger and OpenAPI documents have different response codes.")
    if _schema_names(swagger, True) != _schema_names(openapi, False):
        report.error("cross-format-schemas", "Swagger and OpenAPI documents have different schema names.")
    if _required_by_schema(swagger, True) != _required_by_schema(openapi, False):
        report.error("cross-format-required", "Swagger and OpenAPI documents have different required fields.")


def parse_mapping(text: str, report: Report) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    headers: list[str] | None = None
    for line_number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip().replace("\\|", "|") for cell in stripped.strip("|").split("|")]
        normalized = [cell.lower() for cell in cells]
        if headers is None:
            headers = normalized
            continue
        if all(set(cell) <= {"-", ":"} for cell in normalized):
            continue
        if len(cells) < len(MAPPING_COLUMNS):
            report.error("invalid-mapping-row", f"Mapping row {line_number} has too few columns.", f"mapping:{line_number}")
            continue
        row = dict(zip(headers, cells))
        missing = [column for column in MAPPING_COLUMNS if column not in row]
        if missing:
            report.error(
                "missing-mapping-column",
                f"Mapping table is missing columns: {', '.join(missing)}.",
                f"mapping:{line_number}",
            )
            continue
        row["_line"] = str(line_number)
        rows.append(row)
    if headers is None:
        report.error("missing-mapping-table", "mapping-analysis.md has no Markdown table.")
    return rows


def validate_mapping_rows(rows: list[dict[str, str]], report: Report) -> None:
    for row in rows:
        location = f"mapping:{row.get('_line', '?')}"
        field = row.get("cobol field", "")
        status = row.get("status", "")
        if not field:
            report.error("missing-mapping-field", f"{location} has no COBOL field.", location)
        if status not in VALID_STATUSES:
            report.error("invalid-mapping-status", f"{location} has invalid status {status!r}.", location)
        if row.get("required", "").lower() not in {"yes", "no", "-"}:
            report.error("invalid-required-flag", f"{location} required must be yes or no.", location)
        if row.get("required", "").lower() == "yes" and row.get("evidence", "").strip() in {"", "-"}:
            report.error("missing-required-evidence", f"{location} marks {field} required without evidence.", location)
        if status == "excluded":
            notes = row.get("notes", "").strip()
            if not notes:
                report.error("missing-exclusion-reason", f"{location} excludes {field} without a reason.", location)


def _copybook_fields(parsed: ParsedCopybook) -> dict[str, Any]:
    return {item.name.upper(): item for item in parsed.walk()}


def validate_mapping_coverage(
    rows: list[dict[str, str]],
    copybooks: Iterable[str | Path],
    report: Report,
) -> None:
    if not copybooks:
        return
    covered = {row.get("cobol field", "").upper() for row in rows}
    for copybook in copybooks:
        parsed = CopybookParser().parse(copybook)
        if any(item.severity == "error" for item in parsed.diagnostics):
            for item in parsed.diagnostics:
                if item.severity == "error":
                    report.error(item.code, item.message, f"{item.source}:{item.line}")
            continue
        for name, item in _copybook_fields(parsed).items():
            if name not in covered:
                report.error(
                    "field-not-in-mapping",
                    f"Copybook field {item.name} is missing from mapping-analysis.md.",
                    item.source,
                )
        for row in rows:
            field = row.get("cobol field", "").upper()
            item = _copybook_fields(parsed).get(field)
            if item is None:
                continue
            if item.redefines and row.get("status") == "mapped":
                report.warning(
                    "unreviewed-redefines",
                    f"{item.name} REDEFINES {item.redefines} but is marked mapped.",
                    item.source,
                )


def validate_contract(
    swagger_path: str | Path | None = None,
    openapi_path: str | Path | None = None,
    mapping_path: str | Path | None = None,
    copybooks: Iterable[str | Path] = (),
    context_root: str | None = None,
) -> Report:
    report = Report()
    copybook_list = [Path(item) for item in copybooks]
    swagger: dict[str, Any] | None = None
    openapi: dict[str, Any] | None = None
    if swagger_path is not None:
        swagger = load_document(swagger_path, report)
        if swagger is not None:
            validate_swagger(swagger, report, context_root)
    if openapi_path is not None:
        openapi = load_document(openapi_path, report)
        if openapi is not None:
            validate_openapi(openapi, report, context_root)
    if swagger is not None and openapi is not None:
        compare_contracts(swagger, openapi, report)
    if mapping_path is not None:
        text = _read_text(Path(mapping_path), report)
        if text:
            rows = parse_mapping(text, report)
            validate_mapping_rows(rows, report)
            validate_mapping_coverage(rows, copybook_list, report)
    elif copybook_list:
        report.warning("missing-mapping", "Copybooks were supplied without mapping-analysis.md.")
    report.stats = {
        "swagger": str(swagger_path) if swagger_path else "",
        "openapi": str(openapi_path) if openapi_path else "",
        "mapping": str(mapping_path) if mapping_path else "",
        "copybooks": len(copybook_list),
        "errors": len(report.errors),
        "warnings": len(report.warnings),
    }
    return report


def _format_issue(issue: Issue) -> str:
    location = f" ({issue.location})" if issue.location else ""
    return f"[{issue.level.upper()}] {issue.code}: {issue.message}{location}"


def print_report(report: Report, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return
    for issue in report.errors:
        print(_format_issue(issue), file=sys.stderr)
    for issue in report.warnings:
        print(_format_issue(issue), file=sys.stderr)
    for issue in report.info:
        print(_format_issue(issue), file=sys.stderr)
    status = "PASS" if report.ok else "FAIL"
    print(
        f"{status}: {report.stats.get('errors', 0)} errors, "
        f"{report.stats.get('warnings', 0)} warnings."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate z/OS Connect Swagger, OpenAPI, and mapping artifacts.")
    parser.add_argument("--swagger", help="Swagger 2.0 JSON file.")
    parser.add_argument("--openapi", help="OpenAPI 3.0 JSON or YAML file.")
    parser.add_argument("--mapping", help="mapping-analysis.md file.")
    parser.add_argument("--copybook", action="append", default=[], help="Copybook covered by the mapping. Repeatable.")
    parser.add_argument("--context-root", help="Expected z/OS Connect context root.")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not any((args.swagger, args.openapi, args.mapping)):
        parser.error("At least one of --swagger, --openapi, or --mapping is required.")
    report = validate_contract(
        swagger_path=args.swagger,
        openapi_path=args.openapi,
        mapping_path=args.mapping,
        copybooks=args.copybook,
        context_root=args.context_root,
    )
    print_report(report, args.json)
    if report.errors:
        return 1
    if args.strict and report.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
