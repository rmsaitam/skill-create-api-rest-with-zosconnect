---
description: Analyze a COBOL copybook and report fields, types, arrays, REDEFINES, ODO, COPY dependencies, and JSON mapping risks.
argument-hint: "<copybook> [--copybook-path <dir>] [--free-format] [--json]"
---

# Analyze Copybook

Analyze a COBOL copybook without generating a contract.

## Instructions

- Run the bundled parser from the skill directory:

  ```bash
  python3 <path-to-skill>/scripts/copybook_parser.py <copybook> \
    --copybook-path <dir> --json
  ```

- Report the hierarchy, levels, PIC clauses, USAGE, SIGN, OCCURS/ODO,
  REDEFINES, COPY dependencies, level-88 condition names, and field lengths.
- Highlight fields that cannot be mapped directly to JSON.
- Highlight ambiguous `REDEFINES` and `OCCURS DEPENDING ON` structures that
  require a developer decision.
- Do not infer business rules, required fields, or field names.
- Do not modify the copybook.
- Return a concise summary plus the path to the machine-readable report when
  `--json` is used.
