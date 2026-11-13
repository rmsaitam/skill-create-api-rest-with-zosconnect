# IBM z/OS Connect compatibility

This reference lists the documented compatibility rules the skill applies. It is
not a substitute for the IBM documentation for the target release. Always confirm
the release, feature, tool, and service type before certifying a contract.

## Compatibility claim policy

Static validation can prove that a contract follows the documented syntax and
semantic restrictions. It cannot prove runtime compatibility.

The skill therefore separates:

- **validated** — the rule is confirmed by `validate_contract.py` against the
  documented restrictions;
- **toolchain-required** — the item must be imported or built with z/OS Connect
  Designer, the API provider/requester Gradle plug-in, or the build toolkit
  (`zconbt`) for the target release;
- **needs-review** — the contract contains a decision that only a human can make
  (ambiguous `REDEFINES`, ODO counter exposure, level-88 enum, required fields,
  naming, security).

Never change a `toolchain-required` item to `validated` without evidence.

## Release and feature gates

| Capability | Minimum release / condition |
| --- | --- |
| OpenAPI 3.0 API provider | z/OS Connect 3.0.55 with `zosConnect-3.0` |
| OpenAPI 2.0 API provider, API-first | z/OS Connect 3.0.100 with `zosConnect-3.0` |
| OpenAPI 2.0 API requester on `zosConnect-3.0` | z/OS Connect 3.0.99 |
| OpenAPI 3.0 API requester on `zosConnect-3.0` | z/OS Connect 3.0.x with `zosConnect-3.0` |
| `additionalProperties` for API requester | z/OS Connect 3.0.87 |
| `PATCH` for API requester | z/OS Connect 3.0.87 |
| OpenAPI 3.1 | Not supported by z/OS Connect 3.0 |

z/OS Connect 2.0 continues to use the API toolkit, the build toolkit, and the
`zosConnect-2.0` feature with Swagger 2.0.

## API project file versions

The `request.yaml` and `response_nnn.yaml` mapping files have versions. Use the
version supported by the target release and Gradle plug-in.

| Mapping file version | Minimum server release | Minimum provider Gradle plug-in | Minimum requester Gradle plug-in |
| --- | --- | --- | --- |
| 1.2 | 3.0.91 | 1.4.9 | 1.2.3 |
| 1.1 | 3.0.87 | 1.4.6 | 1.2.0 |
| 1.0 | 3.0.55 | 1.0.0 | 1.0.0 |

Older versions remain supported by the server, but new function may require a
newer file version.

## OpenAPI 3.0 support for API provider

The documented restrictions for z/OS Connect Designer are:

- response range definitions `1XX`, `2XX`, `3XX`, `4XX`, and `5XX` are not
  supported; use explicit codes;
- `HEAD` and `TRACE` operations are ignored;
- remote or URL `$ref` values are not supported; only local references;
- when mapping array items, only the immediate parent array fields are available
  for mapping.

OpenAPI 3.1 is not supported.

## Composite types

- `allOf`, `anyOf`, and `oneOf` are not supported as direct descendants of an
  object property.
- A composite type must not contain a `properties` block. Use a separate object
  type and reference it. IBM documents this as `BAQP0034E` for the API requester.
- The build toolkit historically produced an empty object when composites were
  used as object properties. Treat every composite as `toolchain-required` until
  the target release confirms it.

## Types and formats

The API provider Gradle plug-in documents the following combinations:

| Type | Formats |
| --- | --- |
| `integer` | `int32`, `int64` |
| `number` | `float`, `double`, `decimal` |
| `string` | all string formats |
| `boolean` | no format |

Notes:

- `int64` and `double` are the default formats for their types.
- `decimal` is a schema extension for COBOL packed decimals.
- All string formats are accepted. The format does not affect COBOL
  transformation and may be ignored.
- `format` does not apply to `boolean`.
- `null` is not a type in OpenAPI 3.0. Use `nullable: true` only with an
  explicit `type` and only when the target toolchain accepts it.

## Arrays

- `items` is mandatory.
- Fixed `OCCURS n` → `minItems = maxItems = n`.
- `OCCURS n TO m DEPENDING ON` → `minItems = n`, `maxItems = m`.
- ODO counters are computed on input and are not returned as business fields on
  output.
- The ODO subject must exist in the same structure as the referencing object.
- Nested arrays and arrays of composite types require `toolchain-required`
  validation.
- Arrays as query parameters require a release that supports them; confirm the
  target release.

## additionalProperties

- Supported for API requesters from z/OS Connect 3.0.87.
- Defined only inside an object schema.
- The generated COBOL/PL/I uses an array of property name/value strings; the
  default array size is 20 and the default property size is 255.
- Do not assume API provider support at the same release without confirming the
  documentation.

## PATCH

- Supported for API requesters from z/OS Connect 3.0.87 (`RFC 6902` and
  `RFC 7396`).
- Confirm support for the provider path and the service type before generating a
  contract that depends on `PATCH`.

## Context root

The z/OS Connect context root must match the contract:

- OpenAPI 3.0: the path in the `servers` URL;
- Swagger 2.0: the `basePath` value.

A mismatch causes 404 errors at runtime. Record the context root in the API
specification and in the generation report.

## Response codes

- The `responses` object must contain at least one success code.
- Use explicit codes; response ranges are not supported.
- In YAML, quote the response codes (`"200"`, `"400"`).
- Do not invent error codes. Ask the developer and map each code to a schema.

## Security

OpenAPI 3.0 security is not enabled by default in z/OS Connect 3.0.

- Enable the `appSecurity-2.0` feature when authentication and authorization are
  required.
- Specify authorization roles in the OpenAPI 3.0 document for API providers.
- An `invoke` authorization role is added to each API requester WAR file.
- OpenAPI 3 APIs do not support the OpenAPI 2 authorization interceptor or the
  OpenAPI 2 `requireAuth` and `requireSecure` attributes.
- The OpenAPI 3 API requester does not support the OpenAPI 2 identity assertion.
  Pass credentials, such as a PassTicket, from the z/OS application when needed.

Do not add a security scheme that the target environment cannot enforce.

## Service types

Confirm the service type before generating a contract:

- CICS channel and container assets;
- IMS service and IMS large data structure service;
- Db2 service;
- WOLA service;
- REST client service.

The service type affects request/response structure, prefixes, and the mapping
files. The generator produces the REST contract; it does not generate the
service archive or the API archive.

## Known APARs and cautions

- **PH62141**: a composite type that contains a `properties` block is invalid;
  use a separate object type.
- **PH70325**: composite types as direct descendants of object properties were
  not supported by the build toolkit; the case is a permanent restriction.
- **PH37006**: the build toolkit historically ignored `minLength`/`maxLength`
  for JSON string elements and generated `PIC X(255)`. Confirm the fix level of
  the target build toolkit before relying on lengths.
- Array mapping and composite restrictions are the most common causes of import
  or build failures.

## Toolchain evidence

Record the following in `generation-report.md` when available:

- z/OS Connect release and feature;
- API provider/requester Gradle plug-in version;
- z/OS Connect Designer version;
- build toolkit (`zconbt`) version;
- import or build result;
- messages such as `BAQP0034E`, `DFHPI9698E`, or `DFHPI9729E`;
- unresolved warnings.

## IBM references

- Known issues, limitations, and restrictions:
  <https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=notes-known-issues-limitations>
- Capabilities compatibility:
  <https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=reference-zos-connect-capabilities-compatibility>
- What are z/OS Connect API providers:
  <https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=connect-what-are-zos-api-providers>
- Calling APIs from z/OS applications:
  <https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=developing-api-requester>
- OpenAPI 3.0 schemas supported by the Gradle plug-in:
  <https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=glsap-openapi-30-schemas-supported-by-gradle-plug-in>
- Creating a simple OpenAPI 3.0 document:
  <https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=tutorials-creating-simple-openapi-30-document>
- Migrating zosConnect-2.0 APIs to OpenAPI 3.0:
  <https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=30-migrating-openapi-20-openapi-3>
