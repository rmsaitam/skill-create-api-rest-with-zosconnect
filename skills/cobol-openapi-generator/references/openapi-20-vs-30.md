# Swagger 2.0 vs OpenAPI 3.0

The generator builds one internal model and renders it into both formats. The
documents must be semantically equivalent but structurally different.

## Structural comparison

| Concept | Swagger 2.0 | OpenAPI 3.0 |
| --- | --- | --- |
| Version field | `swagger: "2.0"` | `openapi: "3.0.3"` |
| API metadata | `info` | `info` |
| Host and base path | `host`, `basePath`, `schemes` | `servers[].url` |
| Paths | `paths` | `paths` |
| Operation | method under a path | method under a path |
| Operation ID | `operationId` | `operationId` |
| Body parameter | `parameters` entry with `in: body` | `requestBody` |
| Form data | `in: formData` | `requestBody` with form media type |
| Request media type | `consumes` | `requestBody.content` keys |
| Response media type | `produces` | `responses.<code>.content` keys |
| Response schema | `responses.<code>.schema` | `responses.<code>.content.<media>.schema` |
| Definitions | `definitions` | `components.schemas` |
| Parameters reuse | `parameters` | `components.parameters` |
| Responses reuse | `responses` | `components.responses` |
| Security definitions | `securityDefinitions` | `components.securitySchemes` |
| Security requirement | `security` | `security` |
| File upload | `type: file` | `type: string`, `format: binary` |
| Nullable | `x-nullable` (vendor extension) | `nullable: true` |
| Examples | `examples` map | `example` or `examples` object |
| Links and callbacks | not available | available |
| Cookies | not available | `cookie` parameters |

## Rendering rules

### Version

- Swagger 2.0 uses `"swagger": "2.0"`.
- OpenAPI 3.0 uses `"openapi": "3.0.3"` (or another supported 3.0.x patch).
- Never emit OpenAPI 3.1 for z/OS Connect.

### Servers and base path

Swagger 2.0:

```json
{
  "host": "example.com",
  "basePath": "/api/customer",
  "schemes": ["https"]
}
```

OpenAPI 3.0:

```yaml
servers:
  - url: https://example.com/api/customer
```

The context root must match `basePath` or the `servers` path, depending on the
format.

### Request body

Swagger 2.0:

```json
{
  "parameters": [
    {
      "name": "body",
      "in": "body",
      "required": true,
      "schema": {"$ref": "#/definitions/CustomerRequest"}
    }
  ]
}
```

OpenAPI 3.0:

```yaml
requestBody:
  required: true
  content:
    application/json:
      schema:
        $ref: '#/components/schemas/CustomerRequest'
```

### Responses

Swagger 2.0:

```json
{
  "responses": {
    "200": {
      "description": "Customer found",
      "schema": {"$ref": "#/definitions/CustomerResponse"}
    }
  }
}
```

OpenAPI 3.0:

```yaml
responses:
  "200":
    description: Customer found
    content:
      application/json:
        schema:
          $ref: '#/components/schemas/CustomerResponse'
```

### Schemas

- Generate the same logical schema names in both formats.
- Use `$ref: "#/definitions/<Name>"` for Swagger 2.0.
- Use `$ref: "#/components/schemas/<Name>"` for OpenAPI 3.0.
- Do not use external references.
- Do not use composite types as direct descendants of object properties.

### Required fields

`required` is an array of property names. It must contain only names that exist
in `properties`. The generator never infers it from COBOL.

### Arrays

Both formats use the same keywords: `type: array`, `items`, `minItems`, and
`maxItems`. In Swagger 2.0, `items` is still mandatory.

### Formats

Both formats accept `int32`, `int64`, `float`, `double`, and string formats.
`decimal` is used where the target z/OS Connect release supports it.

### Examples

- Swagger 2.0 supports `examples` maps keyed by media type on responses.
- OpenAPI 3.0 supports `example` on a schema or media type and `examples` with
  named example objects.
- Only generate examples from explicit user input or from values that are
  already present in the copybook `VALUE` clause and approved by the developer.
  Never invent customer data.

## Consistency checks

The validator compares both documents for:

- the same path set;
- the same method set per path;
- the same `operationId` set;
- the same request/response schema names;
- the same required fields;
- the same property names and logical types;
- the same success and error codes.

Any divergence is an error.

## What not to translate

- Swagger 2.0 `x-nullable` must not be copied blindly to OpenAPI 3.0
  `nullable`; confirm the target toolchain.
- OpenAPI 3.0 `callbacks`, `links`, cookies, and advanced security flows have no
  direct Swagger 2.0 equivalent. Do not generate them for a 2.0 target.
- OpenAPI 3.0 `oneOf`/`anyOf` do not have safe Swagger 2.0 equivalents. If the
  contract needs them, generate OpenAPI 3.0 only and explain the limitation.
