#!/usr/bin/env python3
"""Generate Swagger 2.0 and OpenAPI 3.0 contracts from COBOL copybooks.

The generator is deterministic: it renders both formats from one internal model
and writes a mapping analysis plus a generation report. It never edits a
copybook and refuses to write outside the output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent
    yaml = None  # type: ignore[assignment]

from copybook_parser import CopybookParser, Field, ParsedCopybook

ALLOWED_METHODS = {"get", "put", "post", "delete", "options", "patch"}
RESPONSE_CODE_RE = re.compile(r"^(?:default|[1-5]\d{2})$")
PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")
SUPPORTED_TYPES = {"string", "integer", "number", "boolean", "object", "array"}
FORMAT_RULES = {
    "integer": {"int32", "int64"},
    "number": {"float", "double", "decimal"},
    "boolean": set(),
}
REQUIRED_API_KEYS = ("title", "version")
REQUIRED_OPERATION_KEYS = ("path", "method", "operationId", "summary")


class GenerationError(Exception):
    def __init__(self, messages: Iterable[str]) -> None:
        self.messages = list(messages)
        super().__init__("; ".join(self.messages))


@dataclass
class Diagnostic:
    severity: str
    code: str
    message: str
    location: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "location": self.location,
        }


@dataclass
class MappingRow:
    field: str
    json_path: str
    json_type: str
    required: str
    evidence: str
    status: str
    notes: str = ""

    def to_markdown(self) -> str:
        values = [
            self.field,
            self.json_path,
            self.json_type,
            self.required,
            self.evidence,
            self.status,
            self.notes,
        ]
        return "| " + " | ".join(_escape_cell(value) for value in values) + " |"


@dataclass
class GenerationResult:
    spec: dict[str, Any]
    swagger: dict[str, Any]
    openapi: dict[str, Any]
    mapping_rows: list[MappingRow]
    diagnostics: list[Diagnostic]
    input_hashes: dict[str, str]
    output_paths: dict[str, Path] = field(default_factory=dict)
    report: str = ""
    mapping: str = ""

    @property
    def errors(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "error"]


def _escape_cell(value: str | int | None) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_tuple(release: str) -> tuple[int, int, int] | None:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", release.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _pascal_case(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    result = ""
    for part in parts:
        if not part:
            continue
        if part.isupper():
            result += part[:1] + part[1:].lower()
        else:
            result += part[:1].upper() + part[1:]
    return result or "Schema"


def _camel_case(name: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", name) if part]
    if not parts:
        return "field"
    first = parts[0].lower()
    rest = [part[:1].upper() + part[1:].lower() for part in parts[1:] if part]
    return first + "".join(rest)


def _json_name(name: str, naming: str) -> str:
    if naming == "preserve":
        return name
    return _camel_case(name)


def _find_field(parsed: ParsedCopybook, name: str) -> Field | None:
    target = name.upper()
    for item in parsed.walk():
        if item.name.upper() == target or item.name.upper().replace("-", "_") == target.replace("-", "_"):
            return item
    return None


def _field_index(parsed: ParsedCopybook) -> dict[str, Field]:
    index: dict[str, Field] = {}
    for item in parsed.walk():
        index.setdefault(item.name.upper(), item)
    return index


class ContractBuilder:
    def __init__(self, spec: dict[str, Any], copybook_paths: Iterable[str | Path] = ()) -> None:
        self.spec = spec
        self.copybook_paths = [Path(item) for item in copybook_paths]
        self.diagnostics: list[Diagnostic] = []
        self.schemas: dict[str, dict[str, Any]] = {}
        self.schema_names: dict[str, str] = {}
        self.mapping_rows: list[MappingRow] = []
        self.parsed: dict[str, ParsedCopybook] = {}
        self.input_hashes: dict[str, str] = {}
        self.required_evidence: dict[str, str] = {}
        self.excluded: dict[str, str] = {}
        self.redefine_decisions: dict[str, str] = {}
        self.odo_decisions: dict[str, bool] = {}
        self.enum_map: dict[str, list[str]] = {}
        self.overrides: dict[str, dict[str, Any]] = {}
        self.examples: dict[str, Any] = {}
        self.needs_review: list[str] = []
        self.assumptions: list[str] = []
        self._parameters_cache: list[dict[str, Any]] | None = None
        self._load_mapping()

    # ------------------------------------------------------------------
    # Mapping configuration
    # ------------------------------------------------------------------
    def _load_mapping(self) -> None:
        mapping = self.spec.get("mapping") or {}
        if not isinstance(mapping, dict):
            self._error("invalid-mapping", "mapping must be an object.")
            mapping = {}
        for entry in mapping.get("required") or []:
            if isinstance(entry, str):
                self._error("missing-required-evidence", f"Required field {entry} has no evidence.")
                continue
            if not isinstance(entry, dict) or "field" not in entry or "evidence" not in entry:
                self._error("invalid-required", "Each required entry needs field and evidence.")
                continue
            field_name = str(entry["field"])
            evidence = str(entry["evidence"]).strip()
            if not evidence or evidence == "-":
                self._error("missing-required-evidence", f"Required field {field_name} has no evidence.")
                continue
            self.required_evidence[field_name.upper()] = evidence
        for entry in mapping.get("exclude") or []:
            if isinstance(entry, str):
                self.excluded[entry.upper()] = "Excluded by configuration."
                continue
            if not isinstance(entry, dict) or "field" not in entry:
                self._error("invalid-exclusion", "Each exclude entry needs field and reason.")
                continue
            self.excluded[str(entry["field"]).upper()] = str(entry.get("reason", "Excluded by configuration."))
        for entry in mapping.get("redefines") or []:
            if not isinstance(entry, dict) or "field" not in entry or "decision" not in entry:
                self._error("invalid-redefines", "Each redefines entry needs field and decision.")
                continue
            self.redefine_decisions[str(entry["field"]).upper()] = str(entry["decision"])
        for entry in mapping.get("odo") or []:
            if not isinstance(entry, dict) or "field" not in entry:
                self._error("invalid-odo", "Each odo entry needs field.")
                continue
            self.odo_decisions[str(entry["field"]).upper()] = bool(entry.get("expose", False))
        for entry in mapping.get("enums") or []:
            if not isinstance(entry, dict) or "field" not in entry or "values" not in entry:
                self._error("invalid-enum", "Each enums entry needs field and values.")
                continue
            values = entry["values"]
            if not isinstance(values, list) or not values:
                self._error("invalid-enum", f"Enum for {entry['field']} needs a non-empty values list.")
                continue
            self.enum_map[str(entry["field"]).upper()] = [str(value) for value in values]
        overrides = mapping.get("fieldOverrides") or []
        if isinstance(overrides, dict):
            overrides = [{"field": key, **value} for key, value in overrides.items()]
        for entry in overrides:
            if not isinstance(entry, dict) or "field" not in entry:
                self._error("invalid-override", "Each field override needs field.")
                continue
            self.overrides[str(entry["field"]).upper()] = entry
        for entry in mapping.get("examples") or []:
            if isinstance(entry, dict) and "field" in entry and "value" in entry:
                self.examples[str(entry["field"]).upper()] = entry["value"]

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def _error(self, code: str, message: str, location: str = "") -> None:
        self.diagnostics.append(Diagnostic("error", code, message, location))

    def _warning(self, code: str, message: str, location: str = "") -> None:
        self.diagnostics.append(Diagnostic("warning", code, message, location))

    def _info(self, code: str, message: str, location: str = "") -> None:
        self.diagnostics.append(Diagnostic("info", code, message, location))

    def _review(self, message: str) -> None:
        if message not in self.needs_review:
            self.needs_review.append(message)

    @property
    def errors(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "error"]

    # ------------------------------------------------------------------
    # Copybook loading
    # ------------------------------------------------------------------
    def load_copybook(self, path: str | Path, label: str) -> ParsedCopybook:
        copybook_path = Path(path)
        if not copybook_path.is_file():
            self._error("missing-copybook", f"{label} copybook not found: {copybook_path}", str(copybook_path))
            return ParsedCopybook(source=str(copybook_path))
        parser = CopybookParser(copybook_paths=self.copybook_paths)
        parsed = parser.parse(copybook_path)
        self.parsed[str(copybook_path)] = parsed
        self.input_hashes[str(copybook_path)] = _sha256(copybook_path)
        for included in parsed.included:
            included_path = Path(included)
            if included_path.is_file():
                self.input_hashes[str(included_path)] = _sha256(included_path)
        for diagnostic in parsed.diagnostics:
            if diagnostic.severity == "error":
                self._error(diagnostic.code, diagnostic.message, f"{diagnostic.source}:{diagnostic.line}")
            elif diagnostic.severity == "warning":
                self._warning(diagnostic.code, diagnostic.message, f"{diagnostic.source}:{diagnostic.line}")
                if diagnostic.code in {"ambiguous-redefines", "odo-counter", "real-decimal", "unsupported-usage", "copy-replacing", "renames-66"}:
                    self._review(diagnostic.message)
            else:
                self._info(diagnostic.code, diagnostic.message, f"{diagnostic.source}:{diagnostic.line}")
        return parsed

    # ------------------------------------------------------------------
    # Schema generation
    # ------------------------------------------------------------------
    def _schema_name(self, parsed: ParsedCopybook, hint: str) -> str:
        if hint:
            base = _pascal_case(hint)
        elif parsed.fields:
            base = _pascal_case(parsed.fields[0].name)
        else:
            base = "Payload"
        name = base
        index = 2
        while name in self.schemas and self.schema_names.get(name) != parsed.source:
            name = f"{base}{index}"
            index += 1
        self.schema_names[name] = parsed.source
        return name

    def _is_required(self, item: Field) -> bool:
        return item.name.upper() in self.required_evidence or _path_key(item) in self.required_evidence

    def _is_excluded(self, item: Field) -> bool:
        return item.name.upper() in self.excluded or _path_key(item) in self.excluded

    def _resolve_redefines(self, parsed: ParsedCopybook) -> None:
        for item in parsed.walk():
            if not item.redefines:
                continue
            decision = self.redefine_decisions.get(item.name.upper())
            if decision is None:
                self._review(
                    f"{item.name} REDEFINES {item.redefines}: add an explicit decision to mapping.redefines."
                )
                self.excluded[item.name.upper()] = "Ambiguous REDEFINES; excluded pending decision."
                continue
            normalized = decision.lower().replace("_", "-")
            self.redefine_decisions[item.name.upper()] = normalized
            if normalized == "use-first-view":
                self.excluded[item.name.upper()] = "REDEFINES: first view selected."
            elif normalized == "use-redefine-view":
                self.excluded[item.redefines.upper()] = "REDEFINES: redefining view selected."
            elif normalized == "exclude-all":
                self.excluded[item.name.upper()] = "REDEFINES: all views excluded."
                self.excluded[item.redefines.upper()] = "REDEFINES: all views excluded."
            elif normalized == "one-of":
                self._error(
                    "unsupported-composite",
                    f"{item.name}: one-of REDEFINES is not generated automatically because z/OS Connect does not support composites as direct object properties.",
                    parsed.source,
                )
                self.excluded[item.name.upper()] = "Unsupported composite REDEFINES."
            else:
                self._error(
                    "invalid-redefine-decision",
                    f"{item.name}: unknown decision {decision!r}. Use use-first-view, use-redefine-view, exclude-all, or one-of.",
                    parsed.source,
                )

    def _resolve_odo(self, parsed: ParsedCopybook) -> None:
        fields = _field_index(parsed)
        for item in parsed.walk():
            if not item.depending_on:
                continue
            counter = fields.get(item.depending_on.upper())
            if counter is None:
                self._error(
                    "missing-odo-counter",
                    f"{item.name} depends on {item.depending_on}, which is not in the same parsed copybook.",
                    parsed.source,
                )
                continue
            expose = self.odo_decisions.get(counter.name.upper(), False)
            if not expose:
                self.excluded[counter.name.upper()] = (
                    f"ODO counter for {item.name}; computed from the array and not exposed."
                )
            if counter.name.upper() not in self.odo_decisions:
                self._review(
                    f"{counter.name} is an ODO counter. Confirm whether it must be exposed; it is excluded by default."
                )

    def build_schema(self, parsed: ParsedCopybook, hint: str = "") -> tuple[str, dict[str, Any]]:
        self._resolve_redefines(parsed)
        self._resolve_odo(parsed)
        name = self._schema_name(parsed, hint)
        roots = [item for item in parsed.fields if not item.is_condition and not item.is_filler]
        if not roots:
            self._error("empty-schema", f"No usable fields found for {hint or parsed.source}.", parsed.source)
            schema: dict[str, Any] = {"type": "object", "properties": {}}
        elif len(roots) == 1:
            schema = self._field_schema(roots[0], as_property=False) or {"type": "object"}
        else:
            properties: dict[str, Any] = {}
            required: list[str] = []
            for root in roots:
                child = self._field_schema(root, as_property=True)
                if child is None:
                    continue
                prop = _json_name(root.name, self._naming())
                properties[prop] = child
                if self._is_required(root):
                    required.append(prop)
            schema = {"type": "object", "properties": properties}
            if required:
                schema["required"] = required
        self.schemas[name] = schema
        return name, schema

    def _naming(self) -> str:
        mapping = self.spec.get("mapping") or {}
        naming = str(mapping.get("naming", "camelCase")) if isinstance(mapping, dict) else "camelCase"
        if naming not in {"preserve", "camelCase"}:
            self._error("invalid-naming", f"mapping.naming must be preserve or camelCase, got {naming!r}.")
            return "camelCase"
        return naming

    def _field_schema(self, item: Field, as_property: bool = False) -> dict[str, Any] | None:
        if item.is_filler:
            self.excluded[item.name.upper()] = "FILLER field."
            return None
        if item.is_condition:
            return None
        if self._is_excluded(item):
            return None
        override = self.overrides.get(item.name.upper()) or self.overrides.get(_path_key(item))
        if item.is_group:
            properties: dict[str, Any] = {}
            required: list[str] = []
            for child in item.children:
                if child.is_condition:
                    continue
                child_schema = self._field_schema(child, as_property=True)
                if child_schema is None:
                    continue
                prop_name = _json_name(child.name, self._naming())
                if prop_name in properties:
                    self._error(
                        "duplicate-property",
                        f"Duplicate JSON property {prop_name} in {item.name}.",
                        item.source,
                    )
                    continue
                properties[prop_name] = child_schema
                if self._is_required(child):
                    required.append(prop_name)
            schema: dict[str, Any] = {"type": "object", "properties": properties}
            if required:
                schema["required"] = required
            if override:
                self._apply_override(schema, override, item)
            if item.is_array:
                return self._array_schema(item, schema)
            return schema
        schema = self._primitive_schema(item, override)
        if schema is None:
            return None
        if item.is_array:
            return self._array_schema(item, schema)
        return schema

    def _primitive_schema(self, item: Field, override: dict[str, Any] | None) -> dict[str, Any] | None:
        json_type = item.json_type()
        if json_type in {"condition", "unknown", "unsupported"}:
            self._review(f"{item.name} has no direct JSON mapping (type {json_type!r}).")
            self.excluded[item.name.upper()] = f"Unsupported COBOL mapping ({json_type})."
            return None
        schema: dict[str, Any] = {"type": json_type}
        fmt = item.json_format()
        if fmt and json_type in {"integer", "number"}:
            schema["format"] = fmt
        if json_type == "string":
            length = item.max_length()
            if length:
                schema["maxLength"] = length
        if json_type == "number" and item.json_format() == "decimal":
            scale = item.decimal_scale()
            digits = item.digit_count()
            if scale is not None:
                schema["multipleOf"] = 10 ** (-scale) if scale else 1
            if digits is not None:
                limit = 10 ** max(digits - (scale or 0), 0) - 10 ** (-(scale or 0))
                schema["maximum"] = limit
                picture = (item.pic or "").upper()
                schema["minimum"] = -limit if "S" in picture else 0
        enum_values = self.enum_map.get(item.name.upper())
        if enum_values:
            schema["enum"] = enum_values
        example = self.examples.get(item.name.upper())
        if example is not None:
            schema["example"] = example
        if override:
            self._apply_override(schema, override, item)
        return schema

    def _array_schema(self, item: Field, item_schema: dict[str, Any]) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": "array", "items": item_schema}
        if item.occurs_min is not None:
            schema["minItems"] = item.occurs_min
        if item.occurs_max is not None:
            schema["maxItems"] = item.occurs_max
        if item.depending_on:
            self._review(
                f"{item.name} is a variable array (OCCURS DEPENDING ON {item.depending_on}); confirm limits and nested-array support."
            )
        return schema

    def _apply_override(self, schema: dict[str, Any], override: dict[str, Any], item: Field) -> None:
        if "type" in override:
            new_type = str(override["type"])
            if new_type not in SUPPORTED_TYPES:
                self._error("unsupported-override-type", f"{item.name}: unsupported override type {new_type!r}.", item.source)
            else:
                schema.clear()
                schema["type"] = new_type
        if "format" in override:
            schema["format"] = str(override["format"])
        if "description" in override:
            schema["description"] = str(override["description"])
        if "maxLength" in override:
            schema["maxLength"] = int(override["maxLength"])
        if "example" in override:
            schema["example"] = override["example"]
        if "enum" in override and isinstance(override["enum"], list):
            schema["enum"] = [str(value) for value in override["enum"]]
        self._info("field-override", f"{item.name}: field override applied.", item.source)

    # ------------------------------------------------------------------
    # Mapping analysis
    # ------------------------------------------------------------------
    def build_mapping_rows(self, parsed: ParsedCopybook, schema_name: str = "") -> list[MappingRow]:
        del schema_name
        rows: list[MappingRow] = []
        self._walk_rows(parsed.fields, "", rows, parent=None, forced_exclusion=None)
        return rows

    def _walk_rows(
        self,
        items: Iterable[Field],
        prefix: str,
        rows: list[MappingRow],
        parent: Field | None,
        forced_exclusion: str | None,
    ) -> None:
        for item in items:
            if item.is_condition:
                mapped = bool(parent and parent.name.upper() in self.enum_map)
                rows.append(
                    MappingRow(
                        field=item.name,
                        json_path=f"enum:{parent.name}" if mapped and parent else "-",
                        json_type="enum" if mapped else "condition",
                        required="no",
                        evidence="-",
                        status="mapped" if mapped else "needs-review",
                        notes=(
                            f"Level 88 values applied to {parent.name}."
                            if mapped and parent
                            else "Level 88 condition not confirmed as an enum."
                        ),
                    )
                )
                continue
            path = f"{prefix}.{_json_name(item.name, self._naming())}" if prefix else _json_name(item.name, self._naming())
            exclusion = forced_exclusion or (
                self.excluded.get(item.name.upper()) if self._is_excluded(item) else None
            )
            if item.is_filler:
                exclusion = "FILLER field."
            if exclusion:
                rows.append(
                    MappingRow(
                        field=item.name,
                        json_path="-",
                        json_type="-",
                        required="no",
                        evidence="-",
                        status="excluded",
                        notes=exclusion,
                    )
                )
                self._walk_rows(item.children, path, rows, item, exclusion)
                continue
            required = "yes" if self._is_required(item) else "no"
            evidence = self.required_evidence.get(item.name.upper(), "-")
            status = "mapped"
            notes = ""
            if item.redefines:
                decision = self.redefine_decisions.get(item.name.upper())
                if decision is None:
                    status = "needs-review"
                    notes = f"REDEFINES {item.redefines} requires a decision."
                else:
                    notes = f"REDEFINES {item.redefines}: {decision}."
            if item.depending_on:
                status = "needs-review"
                notes = f"OCCURS DEPENDING ON {item.depending_on}; confirm runtime cardinality."
            if item.is_array:
                display_path = f"{path} (array)"
            elif item.is_group:
                display_path = f"{path} (object)"
            else:
                display_path = path
            rows.append(
                MappingRow(
                    field=item.name,
                    json_path=display_path,
                    json_type=_display_type(item),
                    required=required,
                    evidence=evidence,
                    status=status,
                    notes=notes,
                )
            )
            if item.children:
                self._walk_rows(item.children, path, rows, item, None)

    def mapping_markdown(self, parsed_list: Iterable[ParsedCopybook]) -> str:
        rows: list[MappingRow] = []
        for parsed in parsed_list:
            rows.extend(self.build_mapping_rows(parsed))
        lines = [
            "# Mapping analysis",
            "",
            "Generated by the COBOL OpenAPI Generator. Every row is a decision that",
            "must be reviewed. `required` is only set when evidence was supplied.",
            "",
            "| COBOL field | JSON path | JSON type | Required | Evidence | Status | Notes |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in rows:
            lines.append(row.to_markdown())
        if not rows:
            lines.append("| - | - | - | - | - | - | No fields parsed. |")
        return "\n".join(lines).rstrip() + "\n"

    # ------------------------------------------------------------------
    # Document rendering
    # ------------------------------------------------------------------
    def build(self) -> GenerationResult:
        raw_api = self.spec.get("api") or {}
        raw_operation = self.spec.get("operation") or {}
        self._validate_api(raw_api, raw_operation)
        api = raw_api if isinstance(raw_api, dict) else {}
        operation = raw_operation if isinstance(raw_operation, dict) else {}
        self._validate_zos_connect(api, operation)
        request = self.spec.get("request") or {}
        responses = self.spec.get("responses") or []
        parsed_for_mapping: list[ParsedCopybook] = []
        request_schema_name: str | None = None
        if request:
            copybook = request.get("copybook")
            if not copybook:
                self._error("missing-request-copybook", "request.copybook is required when request is present.")
            else:
                parsed = self.load_copybook(copybook, "request")
                parsed_for_mapping.append(parsed)
                schema_hint = str(request.get("schemaName") or f"{operation.get('operationId', 'Operation')}Request")
                request_schema_name, _ = self.build_schema(parsed, schema_hint)
        response_schemas: list[tuple[str, str, str, str | None]] = []
        for index, response in enumerate(responses):
            if not isinstance(response, dict):
                self._error("invalid-response", f"responses[{index}] must be an object.")
                continue
            code = str(response.get("code", ""))
            description = str(response.get("description", "")).strip()
            if not RESPONSE_CODE_RE.match(code):
                self._error("invalid-response-code", f"Invalid response code {code!r}; use an explicit 3-digit code or default.")
            if not description:
                self._error("missing-response-description", f"Response {code} needs a description.")
            schema_name: str | None = None
            copybook = response.get("copybook")
            if copybook:
                parsed = self.load_copybook(copybook, f"response {code}")
                parsed_for_mapping.append(parsed)
                schema_hint = str(response.get("schemaName") or f"{operation.get('operationId', 'Operation')}{code}Response")
                schema_name, _ = self.build_schema(parsed, schema_hint)
            response_schemas.append(
                (
                    code,
                    description,
                    str(response.get("mediaType") or operation.get("mediaType") or "application/json"),
                    schema_name,
                )
            )
        if not responses:
            self._error("missing-responses", "At least one response is required.")
        if not any(code.startswith("2") for code, _, _, _ in response_schemas):
            self._error("missing-success-response", "At least one 2xx success response is required.")
        for name, schema in self.schemas.items():
            self._validate_schema(schema, f"schema {name}", as_property=False)
        swagger = self._render_swagger(api, operation, request_schema_name, response_schemas)
        openapi = self._render_openapi(api, operation, request_schema_name, response_schemas)
        mapping = self.mapping_markdown(parsed_for_mapping)
        rows: list[MappingRow] = []
        for parsed in parsed_for_mapping:
            rows.extend(self.build_mapping_rows(parsed, ""))
        report = self._render_report(api, operation)
        if self.errors:
            raise GenerationError([item.message for item in self.errors])
        return GenerationResult(
            spec=self.spec,
            swagger=swagger,
            openapi=openapi,
            mapping_rows=rows,
            diagnostics=self.diagnostics,
            input_hashes=self.input_hashes,
            report=report,
            mapping=mapping,
        )

    def _ref(self, name: str, document: str) -> str:
        prefix = "definitions" if document == "swagger" else "components/schemas"
        return f"#/{prefix}/{name}"

    def _output_format(self) -> str:
        output = self.spec.get("output") or {}
        if not isinstance(output, dict):
            output = {}
        value = str(self.spec.get("format") or output.get("format") or "both")
        return value if value in {"both", "swagger2", "openapi3"} else "both"

    def _validate_api(self, api: dict[str, Any], operation: dict[str, Any]) -> None:
        if not isinstance(api, dict):
            self._error("invalid-api", "api must be an object.")
            api = {}
        if not isinstance(operation, dict):
            self._error("invalid-operation", "operation must be an object.")
            operation = {}
        for key in REQUIRED_API_KEYS:
            if not api.get(key):
                self._error("missing-api-field", f"api.{key} is required.")
        for key in REQUIRED_OPERATION_KEYS:
            if not operation.get(key):
                self._error("missing-operation-field", f"operation.{key} is required.")
        method = str(operation.get("method", "")).lower()
        if method and method not in ALLOWED_METHODS:
            self._error("unsupported-method", f"HTTP method {method!r} is not supported. Use get, put, post, delete, options, or patch.")
        path = str(operation.get("path", ""))
        if path and not path.startswith("/"):
            self._error("invalid-path", "operation.path must start with '/'.")
        context_root = api.get("contextRoot") or (self.spec.get("zosConnect") or {}).get("contextRoot")
        if not context_root:
            self._error("missing-context-root", "api.contextRoot is required and must match the z/OS Connect context root.")
        elif not str(context_root).startswith("/"):
            self._error("invalid-context-root", "api.contextRoot must start with '/'.")

    def _validate_zos_connect(self, api: dict[str, Any], operation: dict[str, Any]) -> None:
        zos = self.spec.get("zosConnect") or {}
        if not isinstance(zos, dict):
            self._error("invalid-zos-connect", "zosConnect must be an object.")
            return
        if not isinstance(api, dict):
            api = {}
        if not isinstance(operation, dict):
            operation = {}
        for key in ("release", "feature", "apiType"):
            if not zos.get(key):
                self._error("missing-zos-connect-field", f"zosConnect.{key} is required.")
        feature = str(zos.get("feature") or "")
        if feature and feature not in {"zosConnect-2.0", "zosConnect-3.0"}:
            self._error("invalid-zos-feature", "zosConnect.feature must be zosConnect-2.0 or zosConnect-3.0.")
        api_type = str(zos.get("apiType") or "")
        if api_type and api_type not in {"provider", "requester"}:
            self._error("invalid-zos-api-type", "zosConnect.apiType must be provider or requester.")
        zos_context = zos.get("contextRoot")
        api_context = api.get("contextRoot")
        if zos_context and api_context and str(zos_context) != str(api_context):
            self._error(
                "context-root-mismatch",
                f"api.contextRoot {api_context!r} does not match zosConnect.contextRoot {zos_context!r}.",
            )
        version = _release_tuple(str(zos.get("release") or ""))
        output_format = self._output_format()
        if feature == "zosConnect-2.0" and output_format in {"both", "openapi3"}:
            self._error("unsupported-openapi3", "zosConnect-2.0 does not support OpenAPI 3.0 output.")
        if version and feature == "zosConnect-3.0":
            wanted = {"both": (3, 0, 55), "openapi3": (3, 0, 55), "swagger2": (3, 0, 100)}
            if api_type == "provider" and version < wanted[output_format]:
                self._error(
                    "release-gate",
                    f"z/OS Connect {zos.get('release')} is too old for the requested provider output ({output_format}).",
                )
            if api_type == "requester" and output_format in {"both", "swagger2"} and version < (3, 0, 99):
                self._error(
                    "release-gate",
                    f"Swagger 2.0 API requesters require z/OS Connect 3.0.99 or later; got {zos.get('release')}.",
                )
        method = str(operation.get("method", "")).lower()
        if method == "patch":
            if api_type == "requester" and version and version < (3, 0, 87):
                self._error("release-gate", f"PATCH API requesters require z/OS Connect 3.0.87 or later; got {zos.get('release')}.")
            else:
                self._review("PATCH support must be confirmed with the target z/OS Connect release and service type.")

    def _parameters(self) -> list[dict[str, Any]]:
        if self._parameters_cache is not None:
            return self._parameters_cache
        parameters = self.spec.get("parameters") or []
        if not isinstance(parameters, list):
            self._error("invalid-parameters", "parameters must be a list.")
            self._parameters_cache = []
            return self._parameters_cache
        operation = self.spec.get("operation") or {}
        path = str(operation.get("path", "")) if isinstance(operation, dict) else ""
        path_names = set(PATH_PARAM_RE.findall(path))
        seen: set[tuple[str, str]] = set()
        result: list[dict[str, Any]] = []
        for index, parameter in enumerate(parameters):
            if not isinstance(parameter, dict):
                self._error("invalid-parameter", f"parameters[{index}] must be an object.")
                continue
            name = str(parameter.get("name", ""))
            location = str(parameter.get("in", ""))
            if not name or location not in {"path", "query", "header", "cookie"}:
                self._error("invalid-parameter", f"parameters[{index}] needs name and a valid in value.")
                continue
            if location == "cookie":
                self._error("unsupported-parameter-location", f"Cookie parameter {name} is not supported by z/OS Connect contracts.")
                continue
            if (name, location) in seen:
                self._error("duplicate-parameter", f"Duplicate parameter {name} in {location}.")
                continue
            seen.add((name, location))
            required = bool(parameter.get("required", False))
            if location == "path":
                if name not in path_names:
                    self._error("path-parameter-missing", f"Path parameter {name} does not appear in {path}.")
                required = True
            parameter_type = str(parameter.get("type", "string"))
            if parameter_type not in {"string", "integer", "number", "boolean"}:
                self._error("unsupported-parameter-type", f"Parameter {name} uses unsupported type {parameter_type!r}.")
                parameter_type = "string"
            schema: dict[str, Any] = {"type": parameter_type}
            if parameter.get("format"):
                parameter_format = str(parameter["format"])
                if parameter_type in FORMAT_RULES and parameter_format not in FORMAT_RULES[parameter_type]:
                    self._error(
                        "unsupported-parameter-format",
                        f"Parameter {name} uses unsupported format {parameter_format!r} for {parameter_type}.",
                    )
                else:
                    schema["format"] = parameter_format
            if parameter.get("description"):
                schema["description"] = str(parameter["description"])
            if parameter.get("example") is not None:
                schema["example"] = parameter["example"]
            entry: dict[str, Any] = {"name": name, "in": location, "required": required, "schema": schema}
            if parameter.get("description"):
                entry["description"] = str(parameter["description"])
            result.append(entry)
        missing = path_names - {item["name"] for item in result if item["in"] == "path"}
        for name in sorted(missing):
            self._error("missing-path-parameter", f"Path placeholder {{{name}}} has no path parameter.")
        self._parameters_cache = result
        return result

    def _render_swagger(
        self,
        api: dict[str, Any],
        operation: dict[str, Any],
        request_schema_name: str | None,
        responses: list[tuple[str, str, str, str | None]],
    ) -> dict[str, Any]:
        parameters = []
        for item in self._parameters():
            if item["in"] == "path":
                parameters.append(
                    {
                        "name": item["name"],
                        "in": "path",
                        "required": True,
                        "type": item["schema"].get("type", "string"),
                        **({"format": item["schema"]["format"]} if item["schema"].get("format") else {}),
                        **({"description": item["description"]} if item.get("description") else {}),
                    }
                )
            elif item["in"] in {"query", "header"}:
                parameters.append(
                    {
                        "name": item["name"],
                        "in": item["in"],
                        "required": item.get("required", False),
                        "type": item["schema"].get("type", "string"),
                        **({"format": item["schema"]["format"]} if item["schema"].get("format") else {}),
                        **({"description": item["description"]} if item.get("description") else {}),
                    }
                )
        if request_schema_name:
            parameters.append(
                {
                    "name": "body",
                    "in": "body",
                    "required": bool((self.spec.get("request") or {}).get("required", True)),
                    "schema": {"$ref": self._ref(request_schema_name, "swagger")},
                }
            )
        swagger_responses: dict[str, Any] = {}
        for code, description, _media, schema_name in responses:
            entry: dict[str, Any] = {"description": description}
            if schema_name:
                entry["schema"] = {"$ref": self._ref(schema_name, "swagger")}
            swagger_responses[code] = entry
        path = str(operation.get("path", "/"))
        method = str(operation.get("method", "get")).lower()
        operation_object: dict[str, Any] = {
            "operationId": str(operation.get("operationId", "")),
            "summary": str(operation.get("summary", "")),
            "responses": swagger_responses,
        }
        if operation.get("description"):
            operation_object["description"] = str(operation["description"])
        if operation.get("tags"):
            operation_object["tags"] = list(operation["tags"])
        if parameters:
            operation_object["parameters"] = parameters
        document: dict[str, Any] = {
            "swagger": "2.0",
            "info": {"title": str(api.get("title", "")), "version": str(api.get("version", ""))},
            "paths": {path: {method: operation_object}},
            "definitions": dict(self.schemas),
        }
        if api.get("description"):
            document["info"]["description"] = str(api["description"])
        if api.get("host"):
            document["host"] = str(api["host"])
        if api.get("contextRoot"):
            document["basePath"] = str(api["contextRoot"])
            document["schemes"] = list(api.get("schemes") or ["https"])
        document["consumes"] = [str(operation.get("mediaType") or "application/json")]
        document["produces"] = [str(operation.get("mediaType") or "application/json")]
        return document

    def _render_openapi(
        self,
        api: dict[str, Any],
        operation: dict[str, Any],
        request_schema_name: str | None,
        responses: list[tuple[str, str, str, str | None]],
    ) -> dict[str, Any]:
        parameters = []
        for item in self._parameters():
            if item["in"] == "cookie":
                continue
            parameters.append(
                {
                    "name": item["name"],
                    "in": item["in"],
                    "required": bool(item.get("required", False)) or item["in"] == "path",
                    "schema": {
                        key: value
                        for key, value in item["schema"].items()
                        if key in {"type", "format", "example"}
                    },
                    **({"description": item["description"]} if item.get("description") else {}),
                }
            )
        media_type = str(operation.get("mediaType") or "application/json")
        operation_object: dict[str, Any] = {
            "operationId": str(operation.get("operationId", "")),
            "summary": str(operation.get("summary", "")),
            "responses": {},
        }
        if operation.get("description"):
            operation_object["description"] = str(operation["description"])
        if operation.get("tags"):
            operation_object["tags"] = list(operation["tags"])
        if parameters:
            operation_object["parameters"] = parameters
        if request_schema_name:
            operation_object["requestBody"] = {
                "required": bool((self.spec.get("request") or {}).get("required", True)),
                "content": {media_type: {"schema": {"$ref": self._ref(request_schema_name, "openapi")}}},
            }
        for code, description, response_media, schema_name in responses:
            entry: dict[str, Any] = {"description": description}
            if schema_name:
                entry["content"] = {response_media: {"schema": {"$ref": self._ref(schema_name, "openapi")}}}
            operation_object["responses"][code] = entry
        url = str(api.get("contextRoot") or "")
        if api.get("host"):
            scheme = str((api.get("schemes") or ["https"])[0])
            url = f"{scheme}://{api['host']}{url}"
        document: dict[str, Any] = {
            "openapi": "3.0.3",
            "info": {"title": str(api.get("title", "")), "version": str(api.get("version", ""))},
            "servers": [{"url": url}],
            "paths": {str(operation.get("path", "/")): {str(operation.get("method", "get")).lower(): operation_object}},
            "components": {"schemas": dict(self.schemas)},
        }
        if api.get("description"):
            document["info"]["description"] = str(api["description"])
        return document

    def _render_report(self, api: dict[str, Any], operation: dict[str, Any]) -> str:
        zos = self.spec.get("zosConnect") or {}
        if not isinstance(zos, dict):
            zos = {}
        lines = [
            "# Generation report",
            "",
            "## Inputs",
            "",
        ]
        for path, digest in sorted(self.input_hashes.items()):
            lines.append(f"- `{path}` — SHA-256 `{digest}`")
        if not self.input_hashes:
            lines.append("- No copybooks were loaded.")
        lines.extend(
            [
                "",
                "## Endpoint",
                "",
                f"- Path: `{operation.get('path', '')}`",
                f"- Method: `{str(operation.get('method', '')).upper()}`",
                f"- operationId: `{operation.get('operationId', '')}`",
                f"- API version: `{api.get('version', '')}`",
                f"- Context root: `{api.get('contextRoot', '')}`",
                f"- Output format: `{self._output_format()}`",
                "",
                "## Target",
                "",
                f"- z/OS Connect release: `{zos.get('release', 'not specified')}`",
                f"- Feature: `{zos.get('feature', 'not specified')}`",
                f"- API type: `{zos.get('apiType', 'not specified')}`",
                f"- Service type: `{zos.get('serviceType', 'not specified')}`",
                "",
                "## Decisions and assumptions",
                "",
            ]
        )
        if self.required_evidence:
            for field_name, evidence in sorted(self.required_evidence.items()):
                lines.append(f"- Required `{field_name}`: {evidence}")
        if self.redefine_decisions:
            for field_name, decision in sorted(self.redefine_decisions.items()):
                lines.append(f"- REDEFINES `{field_name}`: {decision}")
        if self.odo_decisions:
            for field_name, expose in sorted(self.odo_decisions.items()):
                lines.append(f"- ODO `{field_name}`: {'exposed' if expose else 'excluded'}")
        if self.assumptions:
            for assumption in self.assumptions:
                lines.append(f"- Assumption: {assumption}")
        if not any([self.required_evidence, self.redefine_decisions, self.odo_decisions, self.assumptions]):
            lines.append("- No explicit decisions recorded.")
        lines.extend(["", "## toolchain-required", ""])
        toolchain = [
            "Import or build the contract with the target z/OS Connect Designer, Gradle plug-in, or zconbt.",
            "Confirm the context root matches the deployed server configuration.",
        ]
        if zos.get("serviceType"):
            toolchain.append(f"Confirm {zos['serviceType']} service mapping and prefixes.")
        if self.enum_map:
            toolchain.append("Confirm level-88 enum values with the service owner.")
        for item in toolchain:
            lines.append(f"- {item}")
        lines.extend(["", "## needs-review", ""])
        if self.needs_review:
            for item in self.needs_review:
                lines.append(f"- {item}")
        else:
            lines.append("- None recorded.")
        lines.extend(["", "## Diagnostics", ""])
        if self.diagnostics:
            for item in self.diagnostics:
                location = f" ({item.location})" if item.location else ""
                lines.append(f"- [{item.severity}] {item.code}: {item.message}{location}")
        else:
            lines.append("- None.")
        lines.extend(
            [
                "",
                "## Validation status",
                "",
                "Static validation has not run yet. Run `validate_contract.py` before",
                "sharing or importing the contract. Runtime compatibility still requires",
                "the target z/OS Connect toolchain.",
            ]
        )
        return "\n".join(lines) + "\n"

    def _validate_schema(self, schema: dict[str, Any], location: str, as_property: bool = False) -> None:
        if not isinstance(schema, dict):
            self._error("invalid-schema", f"{location} must be an object.")
            return
        ref = schema.get("$ref")
        if ref:
            if not str(ref).startswith("#/"):
                self._error("external-reference", f"{location} uses a non-local reference {ref!r}.")
            return
        if as_property and any(key in schema for key in ("allOf", "anyOf", "oneOf")):
            self._error(
                "unsupported-composite",
                f"{location} uses a composite type as an object property; z/OS Connect does not support it.",
            )
        if any(key in schema for key in ("allOf", "anyOf", "oneOf")) and "properties" in schema:
            self._error("composite-with-properties", f"{location} combines a composite with properties.")
        schema_type = schema.get("type")
        if schema_type is None:
            if not any(key in schema for key in ("allOf", "anyOf", "oneOf", "properties", "items")):
                self._warning("missing-type", f"{location} has no type.")
        elif schema_type not in SUPPORTED_TYPES:
            self._error("unsupported-type", f"{location} uses unsupported type {schema_type!r}.")
        if schema_type == "array":
            if "items" not in schema:
                self._error("array-without-items", f"{location} is an array without items.")
            else:
                self._validate_schema(schema["items"], f"{location}.items", as_property=True)
            for key in ("minItems", "maxItems"):
                if key in schema and not isinstance(schema[key], int):
                    self._error("invalid-array-limit", f"{location}.{key} must be an integer.")
            if isinstance(schema.get("minItems"), int) and isinstance(schema.get("maxItems"), int):
                if schema["minItems"] > schema["maxItems"]:
                    self._error("invalid-array-limit", f"{location} has minItems > maxItems.")
        if schema_type == "object":
            properties = schema.get("properties", {})
            if not isinstance(properties, dict):
                self._error("invalid-properties", f"{location}.properties must be an object.")
                properties = {}
            for name, child in properties.items():
                self._validate_schema(child, f"{location}.properties.{name}", as_property=True)
            required = schema.get("required")
            if required is not None:
                if not isinstance(required, list):
                    self._error("invalid-required", f"{location}.required must be a list.")
                else:
                    for name in required:
                        if name not in properties:
                            self._error("required-not-in-properties", f"{location}.required references missing property {name!r}.")
        if schema_type in FORMAT_RULES and "format" in schema:
            fmt = str(schema["format"])
            if schema_type == "boolean":
                self._warning("boolean-format", f"{location} declares a format for a boolean; z/OS Connect ignores it.")
            elif fmt not in FORMAT_RULES[schema_type]:
                self._error("unsupported-format", f"{location} uses unsupported format {fmt!r} for {schema_type}.")
        if schema_type == "string" and "format" in schema:
            pass
        if schema.get("nullable") and schema_type is None:
            self._error("nullable-without-type", f"{location} uses nullable without a type.")
        if "maxLength" in schema and schema_type != "string":
            self._warning("maxlength-on-non-string", f"{location} declares maxLength for a non-string type.")


def _path_key(item: Field) -> str:
    return item.name.upper()


def _display_type(item: Field) -> str:
    json_type = "object" if item.is_group else item.json_type()
    fmt = None if item.is_group else item.json_format()
    rendered = f"{json_type}{'/' + fmt if fmt else ''}"
    if item.is_array:
        return f"array<{rendered}>"
    return rendered


def generate(
    spec_path: str | Path,
    out_dir: str | Path | None = None,
    copybook_paths: Iterable[str | Path] = (),
    output_format: str | None = None,
) -> GenerationResult:
    spec_file = Path(spec_path)
    if not spec_file.is_file():
        raise GenerationError([f"API specification not found: {spec_file}"])
    try:
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GenerationError([f"Invalid JSON in {spec_file}: {error}"]) from error
    if not isinstance(spec, dict):
        raise GenerationError([f"{spec_file} must contain a JSON object."])
    if output_format:
        spec["format"] = output_format
    output = spec.get("output") or {}
    target = Path(out_dir or output.get("dir") or "zosconnect-contract")
    builder = ContractBuilder(spec, copybook_paths=copybook_paths)
    result = builder.build()
    output_format = builder._output_format()
    swagger_path = target / str(output.get("swagger") or "swagger.json")
    openapi_path = target / str(output.get("openapi") or "openapi.yml")
    mapping_path = target / str(output.get("mapping") or "mapping-analysis.md")
    report_path = target / str(output.get("report") or "generation-report.md")
    generated: list[Path] = [mapping_path, report_path]
    if output_format in {"both", "swagger2"}:
        generated.append(swagger_path)
    if output_format in {"both", "openapi3"}:
        generated.append(openapi_path)
    for path in generated:
        if target.resolve() not in path.resolve().parents:
            raise GenerationError([f"Output path escapes the output directory: {path}"])
        for input_path in [*builder.input_hashes, str(spec_file)]:
            if path.resolve() == Path(input_path).resolve():
                raise GenerationError([f"Refusing to overwrite an input file: {path}"])
    if output_format in {"both", "openapi3"} and yaml is None:
        raise GenerationError(["PyYAML is required to write openapi.yml. Install PyYAML>=6.0."])
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise GenerationError([f"Cannot create output directory {target}: {error}"]) from error
    if output_format in {"both", "swagger2"}:
        swagger_path.write_text(json.dumps(result.swagger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if output_format in {"both", "openapi3"}:
        assert yaml is not None
        openapi_path.write_text(
            yaml.safe_dump(result.openapi, sort_keys=False, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
    mapping_path.write_text(result.mapping, encoding="utf-8")
    report_path.write_text(result.report, encoding="utf-8")
    result.output_paths = {
        "mapping": mapping_path,
        "report": report_path,
    }
    if output_format in {"both", "swagger2"}:
        result.output_paths["swagger"] = swagger_path
    if output_format in {"both", "openapi3"}:
        result.output_paths["openapi"] = openapi_path
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Swagger 2.0 and OpenAPI 3.0 contracts from COBOL copybooks.")
    parser.add_argument("--spec", required=True, help="API specification JSON.")
    parser.add_argument("--out", help="Output directory.")
    parser.add_argument("--copybook-path", action="append", default=[], help="Directory for COPY members.")
    parser.add_argument("--format", choices=["both", "swagger2", "openapi3"], help="Output format.")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable summary.")
    args = parser.parse_args(argv)
    try:
        result = generate(args.spec, out_dir=args.out, copybook_paths=args.copybook_path, output_format=args.format)
    except GenerationError as error:
        for message in error.messages:
            print(f"error: {message}", file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                {
                    "status": "pass",
                    "outputs": {key: str(value) for key, value in result.output_paths.items()},
                    "diagnostics": [item.to_dict() for item in result.diagnostics],
                },
                indent=2,
            )
        )
    else:
        print("Generated:")
        for key, value in result.output_paths.items():
            print(f"  {key}: {value}")
        warnings = [item for item in result.diagnostics if item.severity == "warning"]
        if warnings:
            print("Warnings:")
            for item in warnings:
                print(f"  [{item.code}] {item.message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
