# Validation checklist

Use this checklist when Python or PyYAML is unavailable, or to review the result
manually. `validate_contract.py` is the source of truth; this document mirrors
its rules.

## 1. Inputs

- [ ] Request copybook identified.
- [ ] Response copybook identified.
- [ ] Every `COPY` dependency resolved or reported as missing.
- [ ] Related COBOL/CICS/IMS/Db2 program reviewed when available.
- [ ] Copybook paths and SHA-256 hashes recorded.
- [ ] No copybook modified.
- [ ] No secret, credential, token, or personal data included.

## 2. COBOL analysis

- [ ] Levels 01, 05, 10, 49, 66, 77, and 88 reviewed.
- [ ] `PIC` and `USAGE` interpreted.
- [ ] `SIGN` and physical length recorded.
- [ ] `OCCURS` and `OCCURS DEPENDING ON` mapped to arrays with limits.
- [ ] ODO counter excluded or explicitly exposed.
- [ ] Ambiguous `REDEFINES` resolved by the developer or marked `needs-review`.
- [ ] Level 88 mapped to `enum` only with explicit evidence.
- [ ] `FILLER`, control fields, and technical prefixes excluded with reason.
- [ ] Unsupported constructs marked and reported.

## 3. Contract content

- [ ] Endpoint path present and starts with `/`.
- [ ] HTTP method is supported and not `HEAD` or `TRACE`.
- [ ] `operationId` present and unique.
- [ ] `info.title` and `info.version` present.
- [ ] Path parameters declared and marked `required: true`.
- [ ] Query and header parameters declared.
- [ ] Request body present when the method needs one.
- [ ] Every response code explicit; no `1XX`…`5XX` ranges.
- [ ] At least one success response.
- [ ] Error responses have descriptions and schemas.
- [ ] `required` contains only existing properties.
- [ ] Every `required` field has recorded evidence.
- [ ] Descriptions are functional, not invented.
- [ ] Examples are explicit and contain no real personal data.

## 4. z/OS Connect restrictions

- [ ] OpenAPI version is 3.0.x or Swagger 2.0; never 3.1.
- [ ] Only local `$ref` values.
- [ ] No composite type as a direct descendant of an object property.
- [ ] No `properties` block inside `allOf`, `anyOf`, or `oneOf`.
- [ ] Arrays have `items`; fixed and ODO limits are correct.
- [ ] `type: null` is not used.
- [ ] Types and formats are supported: `int32`, `int64`, `float`, `double`,
      `decimal`, supported string formats, `boolean`.
- [ ] Context root matches `basePath` or `servers`.
- [ ] Response codes are quoted in YAML.
- [ ] `additionalProperties` and `PATCH` are within the target release gate.
- [ ] Security scheme and roles are enforceable by the target environment.
- [ ] Service type (CICS, IMS, Db2, WOLA, REST) is recorded.

## 5. Cross-format consistency

- [ ] Swagger 2.0 and OpenAPI 3.0 have the same paths.
- [ ] Same methods per path.
- [ ] Same `operationId` set.
- [ ] Same schema names and logical types.
- [ ] Same `required` fields.
- [ ] Same success and error codes.

## 6. Validation and reporting

- [ ] `validate_contract.py` passed without errors.
- [ ] Warnings reviewed; `--strict` used when required.
- [ ] `mapping-analysis.md` covers every field.
- [ ] `generation-report.md` lists inputs, decisions, assumptions, and hashes.
- [ ] `toolchain-required` items listed.
- [ ] `needs-review` items listed.
- [ ] No claim of runtime compatibility without toolchain evidence.

## 7. Toolchain evidence

- [ ] Target z/OS Connect release and feature recorded.
- [ ] API provider/requester Gradle plug-in version recorded.
- [ ] z/OS Connect Designer version recorded when used.
- [ ] Build toolkit (`zconbt`) version recorded when used.
- [ ] Import/build result and relevant messages recorded.
- [ ] Unresolved warnings reported to the user.
