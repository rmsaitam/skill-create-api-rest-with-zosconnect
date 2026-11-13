---
description: Generate Swagger 2.0 and OpenAPI 3.0 contracts from COBOL copybooks for IBM z/OS Connect.
argument-hint: "[--request <copybook>] [--response <copybook>] [--copybook-path <dir>] [--spec <api-spec.json>] [--format both|swagger2|openapi3] [--out <dir>]"
---

# Generate z/OS Connect Contract

Invoke the `cobol-openapi-generator` skill to analyze COBOL copybooks and
generate `swagger.json`, `openapi.yml`, `mapping-analysis.md`, and
`generation-report.md` for IBM z/OS Connect.

## Instructions

- Collect the request copybook, the response copybook, dependent copybooks, and
  the related COBOL/CICS/IMS/Db2 program when available.
- Parse the copybooks with the bundled parser. Never edit a copybook.
- Interview the developer for endpoint, method, operationId, parameters,
  request/response copybooks, success and error codes, API version, and output
  format. Do not repeat answers already provided.
- Never infer required fields. Require explicit evidence and record it.
- Never auto-resolve an ambiguous `REDEFINES`, an `OCCURS DEPENDING ON` counter,
  or a level-88 `enum`. Ask and record the decision.
- Apply the documented z/OS Connect restrictions for Swagger 2.0 and OpenAPI
  3.0. Do not invent IBM configuration or extensions.
- Generate both formats from the same model with `scripts/generate_contract.py` when `--format both` is used.
- Validate before returning. Resolve the script from the skill directory:

  ```bash
  python3 <path-to-skill>/scripts/validate_contract.py \
    --swagger <out>/swagger.json \
    --openapi <out>/openapi.yml \
    --mapping <out>/mapping-analysis.md \
    --copybook <request-copybook> --copybook <response-copybook>
  ```

- Report generated files, endpoint, method, copybooks, OpenAPI version,
  validations, limitations, and items that require the target z/OS Connect
  toolchain.
- Never claim 100% runtime compatibility without importing or building the
  contract with z/OS Connect Designer, the API provider/requester Gradle plug-in,
  or `zconbt`.

## Input

- `--request <copybook>`: request copybook.
- `--response <copybook>`: response copybook.
- `--copybook-path <dir>`: repeatable search path for `COPY` members.
- `--spec <api-spec.json>`: pre-answered API specification.
- `--format both|swagger2|openapi3`: output format. Default `both`.
- `--out <dir>`: output directory. Default `./zosconnect-contract`.
- `--zos-release <version>`: target z/OS Connect release, for example `3.0.107`.
- `--api-type provider|requester`: target API artifact.
- `--strict`: treat compatibility warnings as failures.

## Output

```text
<out>/swagger.json
<out>/openapi.yml
<out>/mapping-analysis.md
<out>/generation-report.md
```

See `skills/cobol-openapi-generator/references/zos-connect-compatibility.md`
and `skills/cobol-openapi-generator/references/openapi-20-vs-30.md`.
