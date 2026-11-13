# Question bank

Ask only when the answer changes the contract. Do not repeat an answer already
present in the user's request, the copybooks, the program, or the API
specification.

## Inputs

- Which copybook is the request payload?
- Which copybook is the response payload?
- Which copybooks are pulled in by `COPY`?
- Which COBOL, CICS, IMS, or Db2 program implements the operation?
- Is the copybook fixed-format or free-format?
- Are there compiler directives, `EXEC SQL` includes, or CICS `COPY` members
  that change the layout?
- Is there a copybook containing error messages or reason codes?

## Endpoint

- What is the endpoint path?
- Which HTTP method does it use: `GET`, `POST`, `PUT`, `PATCH`, or `DELETE`?
- What is the `operationId`?
- What is the functional description?
- What is the API version?
- What is the context root, `basePath`, or `servers` URL?
- Does the operation return a body, a status only, or a list?

## Parameters

- Which values are path parameters?
- Which values are query parameters?
- Which values are header parameters?
- Which parameters are required, and what is the evidence?
- Which parameter types and formats apply?
- Are any parameters arrays? What are the minimum and maximum sizes?
- Are there defaults or examples?

## Responses

- Which HTTP code means success?
- Which HTTP codes mean client error, server error, not found, conflict, or
  validation failure?
- Does each error response have its own copybook or schema?
- Is there a common error structure?
- Are response codes explicit? Response ranges are not supported.
- Are the response codes quoted in the YAML output?

## Copybook mapping

- Should field names be preserved or converted to camelCase?
- Which fields are `required`, and what proves it?
- Which fields are technical, control, or filler fields that must be excluded?
- How should an ambiguous `REDEFINES` be represented?
- Should the `OCCURS DEPENDING ON` counter be exposed?
- Should a level-88 condition become an `enum`, a `boolean`, or stay excluded?
- How should packed decimals (`COMP-3`), binary (`COMP`/`COMP-5`), and floating
  point (`COMP-1`/`COMP-2`) be represented?
- Are there maximum lengths or truncation rules that differ from the copybook?
- Are there fields whose COBOL name is not meaningful to API consumers?

## z/OS Connect

- Which z/OS Connect release is the target?
- Which feature is enabled: `zosConnect-2.0` or `zosConnect-3.0`?
- Is this an API provider or an API requester?
- Which service type is used: CICS, IMS, Db2, WOLA, or REST client?
- Which OpenAPI version is required: Swagger 2.0, OpenAPI 3.0, or both?
- Which security scheme and roles apply?
- Is `additionalProperties` or `PATCH` required? Which release supports it?
- Has the contract already been imported into z/OS Connect Designer or built
  with the Gradle plug-in or `zconbt`?

## Output and validation

- Where should the artifacts be written?
- Should the generation overwrite existing artifacts?
- Should examples be generated?
- Should warnings fail the build (`--strict`)?
- Who reviews the `needs-review` items?
- Who runs the target toolchain validation?

## Safety

- Do the copybooks or programs contain credentials, tokens, keys, or personal
  data?
- Did any sensitive file get included by mistake?

If the answer to the last question is yes, stop, redact the value, and tell the
user to rotate the secret before generating or sharing a contract.
