# Copybook to JSON mapping

This reference records the mapping rules the generator applies and the cases that
must not be automated. It is based on IBM z/OS Connect documentation; validate
the final result against the target release.

## Principles

1. A copybook describes storage, not an API contract. Do not copy every node.
2. A group becomes an object; an elementary item becomes a property.
3. `OCCURS` becomes an array; `REDEFINES` does not become a silent choice.
4. `required` is a contract decision, not a COBOL fact.
5. A field that cannot be mapped is excluded with a reason, not dropped.
6. Every decision goes into `mapping-analysis.md`.

## IBM-documented mapping

The following table summarizes the mapping documented by IBM for the z/OS
Connect API toolkit. Verify the exact behavior for the target release.

| COBOL construct | JSON schema | Notes |
| --- | --- | --- |
| `PIC X`, `PIC A`, `PIC N`, `PIC G` | `type: string` | `maxLength` derived from the picture |
| `PIC 9(n)` display | `type: integer` | Use `int32` or `int64` according to range |
| `PIC 9(m)V9(n)` implied decimal | `type: number`, `format: decimal` | `minimum`, `maximum`, `multipleOf = 1 / 10^n` |
| `COMP`, `COMP-4`, `BINARY` | `type: number`, `description: decimal` | Range depends on the picture and compiler |
| `COMP-1` | `type: number`, `description: float` | Single precision |
| `COMP-2` | `type: number`, `description: double` | Double precision |
| `COMP-3`, `PACKED-DECIMAL` | `type: number`, `format: decimal` | Packed decimal |
| `OCCURS n TIMES` | `type: array`, `minItems: n`, `maxItems: n` | `items` is mandatory |
| `OCCURS n TIMES PIC X` | `type: array` of `string` with `maxLength: 1` | `minItems = maxItems = n` |
| `OCCURS n TO m TIMES DEPENDING ON t` | `type: array`, `minItems: n`, `maxItems: m` | The ODO counter is not a business field |
| `OCCURS n TO m TIMES DEPENDING ON t PIC X(k)` | array of `string` with `maxLength: k` | `minItems = n`, `maxItems = m` |
| Level 88 | no field | Optional `enum` only with explicit evidence |
| FILLER | excluded | Alignment/padding |
| `POINTER`, `INDEX` | excluded or review | No direct JSON representation |

Real decimals such as `PIC +9(9).9(2)` are not supported. Implied decimals such
as `PIC S9(9)V9(2)` are supported as decimals. Do not treat the two as
interchangeable.

## Required and optional

COBOL does not define JSON optionality. A field can be present in storage and
still be optional in the API. A field can be absent from a request and still be
mandatory for the business operation.

Rules:

- Add a field to `required` only when the developer provides evidence.
- Record the evidence in `mapping-analysis.md` (for example, "business rule
  supplied by the API owner", "validated by the service contract", "mandatory in
  the calling program").
- If evidence is missing, leave the field optional and add a `needs-review` item.
- Do not use `VALUE` clauses, `88` conditions, or `NOT NULL` in a Db2 include as
  proof of JSON requiredness.

## Arrays

- `items` is mandatory in both Swagger 2.0 and OpenAPI 3.0.
- Fixed `OCCURS n` → `minItems = maxItems = n`.
- `OCCURS n TO m DEPENDING ON` → `minItems = n`, `maxItems = m`.
- Do not expose the ODO counter unless the developer explicitly requires it.
- Do not flatten an array of objects into repeated scalar properties.
- Do not generate nested arrays without a review item; immediate-parent mapping
  is a documented z/OS Connect limitation.

## REDEFINES

`REDEFINES` is an overlay. The same bytes have multiple interpretations. Safe
representations are:

1. Choose one view and exclude the others, with the developer's decision.
2. Use `oneOf` with an explicit discriminator, only when the target toolchain
   supports it and the discriminator is known.
3. Exclude all views and expose a neutral field, only with explicit approval.

Never generate both views as independent properties: that produces a contract
that cannot be satisfied. Never guess a discriminator.

## Level 88

A level-88 condition is not a stored value. To generate an `enum`, you need:

- the underlying field;
- the explicit values;
- the developer's confirmation that the enum is the API contract.

Otherwise, exclude the condition and record it as `needs-review`.

## Numeric ranges

For each numeric field, record:

- the picture;
- the usage;
- the digit count;
- whether the value is signed;
- the implied decimal scale;
- the chosen JSON type and format;
- the evidence for `int32` versus `int64` versus `decimal`.

`int32` covers values up to 2,147,483,647; `int64` covers larger values. Packed
decimals and implied decimals must not be rounded silently.

## Sizes and lengths

- `PIC X(n)` → `maxLength: n`.
- `PIC 9(n)` display → `maxLength: n` only when the field is represented as a
  string; prefer `integer` when the API contract allows it.
- National and graphic fields may use a different byte length than character
  count; record the encoding assumption.
- Do not apply a `maxLength` that the target z/OS Connect build toolkit is known
  to ignore. Validate the generated COBOL with the target toolchain.

## Exclusions

Exclude and record:

- `FILLER`;
- ODO counters, unless explicitly required;
- technical prefixes (`LL`, `ZZ`, transaction codes) unless the API contract
  exposes them;
- CICS/IMS/Db2 control fields;
- fields with no stable JSON representation;
- secrets, credentials, tokens, and personal data that must not be exposed.

## IBM references

- COBOL to JSON schema mapping:
  <https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=mapping-cobol-json-schema>
- OpenAPI 3.0 schemas supported by the Gradle plug-in:
  <https://www.ibm.com/docs/en/zos-connect/3.0.0?topic=glsap-openapi-30-schemas-supported-by-gradle-plug-in>
- Using `additionalProperties`:
  <https://www.ibm.com/docs/en/zos-connect/zos-connect/3.0?topic=api-using-additional-properties>
