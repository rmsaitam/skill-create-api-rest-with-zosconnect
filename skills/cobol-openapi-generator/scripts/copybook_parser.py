#!/usr/bin/env python3
"""Parse COBOL copybooks into a normalized JSON-friendly model.

The parser is intentionally conservative: it understands the common copybook
constructs used by IBM z/OS Connect projects and reports everything else as a
diagnostic instead of guessing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

LEVEL_RE = re.compile(r"^\s*(\d{1,2})\s+([A-Za-z0-9_@#$+-]+)(.*)$", re.IGNORECASE)
PIC_RE = re.compile(r"\bPIC(?:TURE)?\s+(?:IS\s+)?([^\s]+)", re.IGNORECASE)
USAGE_RE = re.compile(r"\bUSAGE(?:\s+IS)?\s+([A-Z0-9-]+)", re.IGNORECASE)
SIGN_RE = re.compile(r"\bSIGN(?:\s+IS)?\s+(LEADING|TRAILING)(?:\s+SEPARATE)?", re.IGNORECASE)
OCCURS_RE = re.compile(
    r"\bOCCURS\s+(\d+)(?:\s+TO\s+(\d+))?(?:\s+TIMES?)?"
    r"(?:\s+DEPENDING\s+ON\s+([A-Z0-9_-]+))?",
    re.IGNORECASE,
)
REDEFINES_RE = re.compile(r"\bREDEFINES\s+([A-Z0-9_-]+)", re.IGNORECASE)
VALUE_RE = re.compile(r"\bVALUES?(?:\s+IS|\s+ARE)?\s+(.+)$", re.IGNORECASE)
COPY_RE = re.compile(r"^\s*COPY\s+([A-Z0-9_@#$.-]+)(.*)$", re.IGNORECASE)
QUOTED_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"")

USAGE_KEYWORDS = (
    "COMP-1",
    "COMP-2",
    "COMP-3",
    "COMP-4",
    "COMP-5",
    "COMP",
    "BINARY",
    "PACKED-DECIMAL",
    "DISPLAY-1",
    "DISPLAY",
    "NATIONAL",
    "POINTER",
    "INDEX",
)
USAGE_PATTERN = re.compile(r"\b(" + "|".join(re.escape(k) for k in USAGE_KEYWORDS) + r")\b", re.IGNORECASE)
COPY_SUFFIXES = (".cbl", ".cpy", ".copy", ".cob", ".txt")
SKIP_DIRECTIVES = {"EJECT", "SKIP1", "SKIP2", "SKIP3", "TITLE"}
UNSUPPORTED_USAGE = {"POINTER", "INDEX"}


@dataclass
class Diagnostic:
    severity: str
    code: str
    message: str
    source: str = ""
    line: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "line": self.line,
        }


@dataclass
class Field:
    level: int
    name: str
    source: str = ""
    line: int = 0
    pic: str | None = None
    usage: str | None = None
    sign: str | None = None
    sign_separate: bool = False
    redefines: str | None = None
    value: str | None = None
    condition_values: list[str] = field(default_factory=list)
    occurs_min: int | None = None
    occurs_max: int | None = None
    depending_on: str | None = None
    children: list["Field"] = field(default_factory=list)

    @property
    def is_filler(self) -> bool:
        return self.name.upper() == "FILLER"

    @property
    def is_condition(self) -> bool:
        return self.level == 88

    @property
    def is_group(self) -> bool:
        return any(not child.is_condition for child in self.children)

    @property
    def is_array(self) -> bool:
        return self.occurs_min is not None or self.occurs_max is not None

    @property
    def path(self) -> str:
        return self.name

    def walk(self) -> Iterable["Field"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def to_dict(self, include_source: bool = False) -> dict[str, object]:
        data: dict[str, object] = {
            "level": self.level,
            "name": self.name,
            "kind": "condition" if self.is_condition else ("group" if self.is_group else "field"),
            "pic": self.pic,
            "usage": self.usage,
            "sign": self.sign,
            "signSeparate": self.sign_separate,
            "redefines": self.redefines,
            "value": self.value,
            "occurs": (
                {
                    "min": self.occurs_min,
                    "max": self.occurs_max,
                    "dependingOn": self.depending_on,
                }
                if self.is_array
                else None
            ),
            "jsonType": self.json_type(),
            "format": self.json_format(),
            "maxLength": self.max_length(),
            "digits": self.digit_count(),
            "scale": self.decimal_scale(),
            "children": [child.to_dict(include_source=include_source) for child in self.children],
        }
        if self.condition_values:
            data["conditionValues"] = self.condition_values
        if include_source:
            data["source"] = self.source
            data["line"] = self.line
        return data

    def digit_count(self) -> int | None:
        if not self.pic:
            return None
        count = 0
        for match in re.finditer(r"([9Z*])(?:\((\d+)\))?", self.pic.upper()):
            count += int(match.group(2)) if match.group(2) else 1
        return count or None

    def decimal_scale(self) -> int | None:
        if not self.pic:
            return None
        picture = self.pic.upper()
        if "V" not in picture:
            return 0
        tail = picture.split("V", 1)[1]
        scale = 0
        for match in re.finditer(r"([9Z*])(?:\((\d+)\))?", tail):
            scale += int(match.group(2)) if match.group(2) else 1
        return scale

    def max_length(self) -> int | None:
        if not self.pic:
            return None
        picture = self.pic.upper()
        total = 0
        found = False
        for match in re.finditer(r"([XANG])(?:\((\d+)\))?", picture.replace(" ", "")):
            symbol = match.group(1)
            size = int(match.group(2)) if match.group(2) else 1
            total += size
            found = True
        if found:
            return total
        return self.digit_count()

    def json_type(self) -> str:
        if self.is_condition:
            return "condition"
        if self.is_group:
            return "object"
        usage = (self.usage or "").upper()
        picture = (self.pic or "").upper()
        if usage in UNSUPPORTED_USAGE:
            return "unsupported"
        if usage == "COMP-1":
            return "number"
        if usage == "COMP-2":
            return "number"
        if usage in {"COMP-3", "PACKED-DECIMAL"}:
            return "number"
        if not picture:
            return "unknown"
        if any(symbol in picture for symbol in ("X", "A", "N", "G")):
            return "string"
        if "V" in picture or "P" in picture:
            return "number"
        if any(symbol in picture for symbol in ("9", "Z", "*")):
            digits = self.digit_count() or 0
            return "number" if digits > 18 else "integer"
        return "unknown"

    def json_format(self) -> str | None:
        usage = (self.usage or "").upper()
        if usage == "COMP-1":
            return "float"
        if usage == "COMP-2":
            return "double"
        if usage in {"COMP-3", "PACKED-DECIMAL"}:
            return "decimal"
        if self.json_type() == "number":
            return "decimal"
        if self.json_type() == "integer":
            digits = self.digit_count() or 0
            if digits <= 9:
                return "int32"
            if digits <= 18:
                return "int64"
            return "decimal"
        return None


@dataclass
class ParsedCopybook:
    source: str
    fields: list[Field] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    included: list[str] = field(default_factory=list)

    def walk(self) -> Iterable[Field]:
        for root in self.fields:
            yield from root.walk()

    def to_dict(self, include_source: bool = False) -> dict[str, object]:
        return {
            "source": self.source,
            "included": list(self.included),
            "fields": [item.to_dict(include_source=include_source) for item in self.fields],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


class CopybookParser:
    def __init__(
        self,
        copybook_paths: Iterable[str | Path] = (),
        free_format: bool = False,
        include_source: bool = False,
    ) -> None:
        self.copybook_paths = [Path(item) for item in copybook_paths]
        self.free_format = free_format
        self.include_source = include_source

    def parse(self, path: str | Path) -> ParsedCopybook:
        source_path = Path(path)
        parsed = ParsedCopybook(source=str(source_path))
        if not source_path.is_file():
            parsed.diagnostics.append(
                Diagnostic("error", "missing-copybook", f"Copybook not found: {source_path}", str(source_path))
            )
            return parsed
        try:
            text = source_path.read_text(encoding="utf-8")
        except OSError as error:
            parsed.diagnostics.append(
                Diagnostic("error", "unreadable-copybook", f"Cannot read {source_path}: {error}", str(source_path))
            )
            return parsed
        return self.parse_text(text, source=str(source_path), parsed=parsed)

    def parse_text(self, text: str, source: str = "<string>", parsed: ParsedCopybook | None = None) -> ParsedCopybook:
        parsed = parsed or ParsedCopybook(source=source)
        expanded, included = self._expand_copybooks(text, source, parsed, [])
        parsed.included.extend(included)
        statements = self._statements(expanded, source, parsed)
        self._build_tree(statements, parsed)
        self._validate_tree(parsed)
        return parsed

    def _expand_copybooks(
        self,
        text: str,
        source: str,
        parsed: ParsedCopybook,
        stack: list[str],
    ) -> tuple[str, list[str]]:
        included: list[str] = []
        output: list[str] = []
        skip_exec = False
        for line_number, raw in enumerate(text.splitlines(), start=1):
            code = self._code_part(raw)
            if code is None:
                output.append("")
                continue
            stripped = code.strip()
            upper = stripped.upper()
            if skip_exec:
                if "END-EXEC" in upper:
                    skip_exec = False
                output.append("")
                continue
            if upper.startswith("EXEC "):
                skip_exec = "END-EXEC" not in upper
                parsed.diagnostics.append(
                    Diagnostic(
                        "warning",
                        "embedded-sql-or-cics",
                        f"Embedded statement is not a copybook entry and was skipped: {stripped[:60]}",
                        source,
                        line_number,
                    )
                )
                output.append("")
                continue
            if upper.split(" ", 1)[0] in SKIP_DIRECTIVES:
                output.append("")
                continue
            match = COPY_RE.match(stripped)
            if not match:
                output.append(raw)
                continue
            member = match.group(1).rstrip(".")
            remainder = match.group(2).strip()
            if "REPLACING" in remainder.upper():
                parsed.diagnostics.append(
                    Diagnostic(
                        "warning",
                        "copy-replacing",
                        f"COPY {member} uses REPLACING; replacements are not applied automatically.",
                        source,
                        line_number,
                    )
                )
            member_path = self._find_member(member)
            if member_path is None:
                parsed.diagnostics.append(
                    Diagnostic(
                        "error",
                        "missing-copy-member",
                        f"COPY member not found: {member}",
                        source,
                        line_number,
                    )
                )
                output.append("")
                continue
            key = str(member_path.resolve())
            if key in stack:
                parsed.diagnostics.append(
                    Diagnostic(
                        "error",
                        "copy-cycle",
                        f"COPY cycle detected for member: {member}",
                        source,
                        line_number,
                    )
                )
                output.append("")
                continue
            try:
                member_text = member_path.read_text(encoding="utf-8")
            except OSError as error:
                parsed.diagnostics.append(
                    Diagnostic("error", "unreadable-copy-member", f"Cannot read {member_path}: {error}", source, line_number)
                )
                output.append("")
                continue
            included.append(str(member_path))
            expanded, nested = self._expand_copybooks(member_text, str(member_path), parsed, stack + [key])
            included.extend(nested)
            output.extend(expanded.splitlines())
        return "\n".join(output), included

    def _find_member(self, member: str) -> Path | None:
        candidates: list[Path] = []
        names = [member]
        if not any(member.lower().endswith(suffix) for suffix in COPY_SUFFIXES):
            names.extend(member + suffix for suffix in COPY_SUFFIXES)
        for base in self.copybook_paths or [Path(".")]:
            for name in names:
                candidates.append(base / name)
                candidates.append(base / name.lower())
                candidates.append(base / name.upper())
            if base.is_dir():
                for child in base.iterdir():
                    if child.is_file() and child.name.lower() in {name.lower() for name in names}:
                        candidates.append(child)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _code_part(self, raw: str) -> str | None:
        line = raw.rstrip("\n\r")
        if self.free_format:
            if "*>" in line:
                line = line.split("*>", 1)[0]
            if not line.strip() or line.lstrip().startswith("*"):
                return None
            return line
        if len(line) >= 7 and line[6] in "*/Dd":
            return None
        if len(line) < 7:
            return line if line.strip() else None
        code = line[7:72] if len(line) > 72 else line[7:]
        return code if code.strip() else None

    def _statements(self, text: str, source: str, parsed: ParsedCopybook) -> list[tuple[str, int]]:
        statements: list[tuple[str, int]] = []
        logical: list[tuple[str, int]] = []
        current: list[str] = []
        current_line = 0
        for line_number, raw in enumerate(text.splitlines(), start=1):
            code = self._code_part(raw)
            if code is None:
                continue
            if self.free_format:
                current = [code]
                current_line = line_number
                for piece in self._split_pieces(code):
                    statements.append((piece, current_line))
                continue
            indicator = raw[6] if len(raw) > 6 else " "
            if indicator == "-" and current:
                current.append(code.strip())
                continue
            if current:
                logical.append((" ".join(current), current_line))
            current = [code.strip()]
            current_line = line_number
        if current:
            logical.append((" ".join(current), current_line))
        for line, line_number in logical:
            for piece in self._split_pieces(line):
                statements.append((piece, line_number))
        return statements

    def _split_pieces(self, line: str) -> list[str]:
        text = line.strip()
        if not text:
            return []
        if text.endswith("."):
            text = text[:-1]
        pieces = re.split(r"\.\s+(?=\d{1,2}\s+[A-Za-z])", text)
        return [piece.strip() for piece in pieces if piece.strip()]

    def _build_tree(self, statements: list[tuple[str, int]], parsed: ParsedCopybook) -> None:
        stack: list[Field] = []
        last_field: Field | None = None
        for statement, line_number in statements:
            match = LEVEL_RE.match(statement)
            if not match:
                continue
            level = int(match.group(1))
            name = match.group(2)
            rest = match.group(3)
            field = Field(
                level=level,
                name=name,
                source=parsed.source,
                line=line_number,
                pic=self._match(PIC_RE, rest),
                usage=self._usage(rest),
                sign=self._sign(rest),
                redefines=self._match(REDEFINES_RE, rest),
                value=self._match(VALUE_RE, rest),
            )
            field.sign_separate = bool(re.search(r"\bSIGN\b.*\bSEPARATE\b", rest, re.IGNORECASE))
            occurs = OCCURS_RE.search(rest)
            if occurs:
                field.occurs_min = int(occurs.group(1))
                field.occurs_max = int(occurs.group(2) or occurs.group(1))
                field.depending_on = occurs.group(3).upper() if occurs.group(3) else None
            if level == 88:
                field.condition_values = self._condition_values(rest)
                if last_field is not None:
                    last_field.children.append(field)
                else:
                    parsed.diagnostics.append(
                        Diagnostic("warning", "orphan-88", f"Level 88 {name} has no parent field.", parsed.source, line_number)
                    )
                continue
            if level == 66:
                parsed.diagnostics.append(
                    Diagnostic("warning", "renames-66", f"Level 66 {name} requires manual review.", parsed.source, line_number)
                )
                continue
            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                stack[-1].children.append(field)
            else:
                parsed.fields.append(field)
            stack.append(field)
            last_field = field

    def _validate_tree(self, parsed: ParsedCopybook) -> None:
        if not parsed.fields:
            parsed.diagnostics.append(
                Diagnostic("error", "empty-copybook", "No COBOL entries were found.", parsed.source)
            )
        for item in parsed.walk():
            if item.level == 88:
                continue
            if item.is_filler:
                continue
            if item.pic is None and not item.children:
                parsed.diagnostics.append(
                    Diagnostic(
                        "warning",
                        "group-without-children",
                        f"{item.name} has no PIC and no children.",
                        item.source,
                        item.line,
                    )
                )
            if item.usage and item.usage.upper() in UNSUPPORTED_USAGE:
                parsed.diagnostics.append(
                    Diagnostic(
                        "warning",
                        "unsupported-usage",
                        f"{item.name} uses {item.usage}, which has no direct JSON representation.",
                        item.source,
                        item.line,
                    )
                )
            if item.redefines:
                parsed.diagnostics.append(
                    Diagnostic(
                        "warning",
                        "ambiguous-redefines",
                        f"{item.name} REDEFINES {item.redefines}; an explicit mapping decision is required.",
                        item.source,
                        item.line,
                    )
                )
            if item.depending_on:
                parsed.diagnostics.append(
                    Diagnostic(
                        "warning",
                        "odo-counter",
                        f"{item.name} is OCCURS DEPENDING ON {item.depending_on}; the counter must be reviewed.",
                        item.source,
                        item.line,
                    )
                )
            if item.level == 77:
                parsed.diagnostics.append(
                    Diagnostic(
                        "info",
                        "level-77",
                        f"{item.name} is an independent level-77 item.",
                        item.source,
                        item.line,
                    )
                )
            if item.json_type() == "unknown":
                parsed.diagnostics.append(
                    Diagnostic(
                        "warning",
                        "unknown-type",
                        f"{item.name} has no supported JSON type mapping.",
                        item.source,
                        item.line,
                    )
                )
            if item.json_type() == "number" and item.pic and "." in item.pic and "V" not in item.pic.upper():
                parsed.diagnostics.append(
                    Diagnostic(
                        "warning",
                        "real-decimal",
                        f"{item.name} uses an explicit decimal point, which z/OS Connect does not support as a real decimal.",
                        item.source,
                        item.line,
                    )
                )

    @staticmethod
    def _match(pattern: re.Pattern[str], text: str) -> str | None:
        match = pattern.search(text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _usage(text: str) -> str | None:
        match = USAGE_RE.search(text)
        if match:
            return match.group(1).upper()
        match = USAGE_PATTERN.search(text)
        if match:
            return match.group(1).upper()
        return None

    @staticmethod
    def _sign(text: str) -> str | None:
        match = SIGN_RE.search(text)
        if not match:
            return None
        return match.group(1).upper()

    @staticmethod
    def _condition_values(text: str) -> list[str]:
        match = VALUE_RE.search(text)
        if not match:
            return []
        values: list[str] = []
        for quoted in QUOTED_RE.finditer(match.group(1)):
            values.append(quoted.group(1) if quoted.group(1) is not None else quoted.group(2))
        if not values:
            for token in re.split(r"[\s,]+", match.group(1).strip()):
                if token and token.upper() not in {"VALUE", "VALUES", "IS", "ARE", "THRU", "THROUGH"}:
                    values.append(token)
        return values


def parse_copybook(
    path: str | Path,
    copybook_paths: Iterable[str | Path] = (),
    free_format: bool = False,
) -> ParsedCopybook:
    return CopybookParser(copybook_paths=copybook_paths, free_format=free_format).parse(path)


def _human_summary(parsed: ParsedCopybook) -> str:
    lines = [f"Copybook: {parsed.source}"]
    if parsed.included:
        lines.append("Included:")
        lines.extend(f"  - {item}" for item in parsed.included)
    lines.append("Fields:")
    for root in parsed.fields:
        for item in root.walk():
            if item.level == 88:
                values = ", ".join(item.condition_values)
                lines.append(f"  {item.level:>2} {item.name} (condition: {values})")
                continue
            occurs = ""
            if item.is_array:
                occurs = f" OCCURS {item.occurs_min}..{item.occurs_max}"
                if item.depending_on:
                    occurs += f" DEPENDING ON {item.depending_on}"
            pic = f" PIC {item.pic}" if item.pic else ""
            usage = f" {item.usage}" if item.usage else ""
            lines.append(f"  {item.level:>2} {item.name}{pic}{usage}{occurs} -> {item.json_type()}")
    if parsed.diagnostics:
        lines.append("Diagnostics:")
        for item in parsed.diagnostics:
            location = f" ({item.source}:{item.line})" if item.line else ""
            lines.append(f"  [{item.severity}] {item.code}: {item.message}{location}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse a COBOL copybook into a JSON model.")
    parser.add_argument("copybook", help="Path to the copybook.")
    parser.add_argument("--copybook-path", action="append", default=[], help="Directory for COPY members.")
    parser.add_argument("--free-format", action="store_true", help="Parse free-format COBOL.")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report.")
    parser.add_argument("--include-source", action="store_true", help="Include source file and line in JSON.")
    args = parser.parse_args(argv)

    parsed = CopybookParser(
        copybook_paths=args.copybook_path,
        free_format=args.free_format,
        include_source=args.include_source,
    ).parse(args.copybook)

    if args.json:
        print(json.dumps(parsed.to_dict(include_source=args.include_source), indent=2, ensure_ascii=False))
    else:
        print(_human_summary(parsed))

    return 1 if any(item.severity == "error" for item in parsed.diagnostics) else 0


if __name__ == "__main__":
    sys.exit(main())
