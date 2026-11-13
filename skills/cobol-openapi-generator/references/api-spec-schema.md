# API specification schema

`generate_contract.py` accepts a JSON file that records the interview answers
and the mapping decisions. The file is the single source of truth for the
generation. Command-line options override only paths and output format, not the
business decisions.

## Shape

```json
{
  "api": {
    "title": "Customer API",
    "version": "1.0.0",
    "description": "Customer lookup and maintenance.",
    "contextRoot": "/api/customer",
    "host": "example.com",
    "schemes": ["https"]
  },
  "operation": {
    "path": "/customers/{customerId}",
    "method": "get",
    "operationId": "getCustomer",
    "summary": "Get a customer",
    "description": "Returns a customer by identifier.",
    "tags": ["customers"],
    "mediaType": "application/json"
  },
  "parameters": [
    {
      "name": "customerId",
      "in": "path",
      "required": true,
      "type": "integer",
      "format": "int64",
      "description": "Customer identifier."
    }
  ],
  "request": {
    "copybook": "copybooks/request.cbl",
    "required": true
  },
  "responses": [
    {
      "code": "200",
      "description": "Customer found",
      "copybook": "copybooks/response.cbl"
    },
    {
      "code": "404",
      "description": "Customer not found",
      "copybook": "copybooks/error.cbl"
    }
  ],
  "mapping": {
    "naming": "camelCase",
    "required": [
      {"field": "CUSTOMER-ID", "evidence": "Required by the interface contract."}
    ],
    "exclude": [
      {"field": "FILLER", "reason": "Alignment padding."}
    ],
    "redefines": [
      {"field": "PAYMENT-DATA", "decision": "use-first-view", "reason": "The API only accepts card payments."}
    ],
    "odo": [
      {"field": "ITEM-COUNT", "expose": false, "reason": "The array size is computed from the items."}
    ],
    "enums": [
      {"field": "STATUS-CODE", "values": ["A", "I"], "evidence": "Documented in the interface contract."}
    ]
  },
  "zosConnect": {
    "release": "3.0.107",
    "feature": "zosConnect-3.0",
    "apiType": "provider",
    "serviceType": "CICS",
    "contextRoot": "/api/customer"
  },
  "output": {
    "dir": "zosconnect-contract",
    "swagger": "swagger.json",
    "openapi": "openapi.yml",
    "mapping": "mapping-analysis.md",
    "report": "generation-report.md"
  }
}
```

## Fields

### `api`

| Field | Required | Notes |
| --- | --- | --- |
| `title` | yes | API title |
| `version` | yes | API version, not the z/OS Connect release |
| `description` | no | Functional description |
| `contextRoot` | yes | Must match `basePath` or `servers` path |
| `host` | Swagger 2.0 only | Host name |
| `schemes` | Swagger 2.0 only | Usually `["https"]` |

### `operation`

| Field | Required | Notes |
| --- | --- | --- |
| `path` | yes | Must start with `/` |
| `method` | yes | `get`, `post`, `put`, `patch`, or `delete` |
| `operationId` | yes | Unique across the document |
| `summary` | yes | Short description |
| `description` | no | Functional description |
| `tags` | no | Documentation tags |
| `mediaType` | no | Default `application/json` |

`head` and `trace` are rejected.

### `parameters`

Each parameter follows the OpenAPI parameter object with the subset used by the
generator:

| Field | Required | Notes |
| --- | --- | --- |
| `name` | yes | Parameter name |
| `in` | yes | `path`, `query`, or `header` |
| `required` | yes for path | Path parameters must be required |
| `type` | yes | `string`, `integer`, `number`, or `boolean` |
| `format` | no | Must be supported by z/OS Connect |
| `description` | no | Documentation |
| `example` | no | Explicit example only |

Path parameters must appear in the path template.

### `request` and `responses`

| Field | Required | Notes |
| --- | --- | --- |
| `copybook` | yes | Path to the copybook |
| `required` | no | Default `true` for request bodies |
| `mediaType` | no | Default `application/json` |
| `description` | yes for responses | Response description |

Every response code must be explicit. Do not use `2XX`.

### `mapping`

| Field | Required | Notes |
| --- | --- | --- |
| `naming` | no | `preserve` or `camelCase`; default `camelCase` |
| `required` | no | List of fields with evidence |
| `exclude` | no | List of fields with a reason |
| `redefines` | no | Explicit decision per overlay |
| `odo` | no | Whether to expose the counter |
| `enums` | no | Explicit level-88 mapping |
| `fieldOverrides` | no | Type, format, name, or description override |

Overrides are applied only when explicitly listed in the API specification.
Record the rationale in the review notes and keep the generated
`mapping-analysis.md` with the contract.

### `zosConnect`

| Field | Required | Notes |
| --- | --- | --- |
| `release` | yes | Target release |
| `feature` | yes | `zosConnect-2.0` or `zosConnect-3.0` |
| `apiType` | yes | `provider` or `requester` |
| `serviceType` | no | `CICS`, `IMS`, `Db2`, `WOLA`, or `REST` |
| `contextRoot` | yes | Must match the API context root |

The generator uses these values to apply version gates and to populate
`generation-report.md`.

### `output`

| Field | Required | Notes |
| --- | --- | --- |
| `dir` | no | Output directory |
| `swagger` | no | Default `swagger.json` |
| `openapi` | no | Default `openapi.yml` |
| `mapping` | no | Default `mapping-analysis.md` |
| `report` | no | Default `generation-report.md` |

Output paths must stay inside the output directory. The generator refuses to
overwrite a copybook.

## Validation

The generator and `validate_contract.py` reject:

- missing required fields;
- unknown methods;
- `head` and `trace`;
- response ranges;
- path parameters missing from the template;
- duplicate parameter names with the same `in`;
- unsupported types or formats;
- `required` fields without evidence;
- output paths that escape the output directory.
