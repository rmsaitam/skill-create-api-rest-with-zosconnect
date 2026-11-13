---
description: Validate Swagger 2.0 and OpenAPI 3.0 contracts and copybook mappings for IBM z/OS Connect.
argument-hint: "[--swagger <file>] [--openapi <file>] [--mapping <file>] [--copybook <file>] [--strict] [--json]"
---

# Validate z/OS Connect Contract

Validate contracts produced by the `cobol-openapi-generator` skill before they
are imported or built with IBM z/OS Connect.

## Instructions

- Run the bundled validator from the skill directory:

  ```bash
  python3 <path-to-skill>/scripts/validate_contract.py \
    --swagger <file> --openapi <file> --mapping <file> --copybook <file>
  ```

- Validate JSON and YAML syntax, local `$ref` resolution, unique `operationId`,
  parameters, responses, types and formats, required fields, and HTTP codes.
- Reject OpenAPI 3.1, response ranges, external references, HEAD/TRACE, invalid
  composites, arrays without `items`, and unsupported types or formats.
- Compare Swagger 2.0 and OpenAPI 3.0 when both are provided and report drift.
- Validate `mapping-analysis.md` against the copybooks: every field must be
  mapped or explicitly excluded with a reason.
- Use `--strict` to treat warnings as failures and `--json` for a
  machine-readable report.
- Never modify the contracts unless the user asks for fixes. Re-run the
  validator after any fix.
- Report `validated`, `toolchain-required`, and `needs-review` items separately.
- Never declare runtime compatibility with z/OS Connect from static validation
  alone.
