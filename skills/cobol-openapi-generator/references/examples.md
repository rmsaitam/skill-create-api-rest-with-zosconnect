# Examples

These examples show the expected input and output shape. They are illustrative;
the generated files are always validated by `validate_contract.py`.

## Request copybook

```cobol
       01 CUSTOMER-REQUEST.
          05 CUSTOMER-ID       PIC 9(9).
          05 CUSTOMER-NAME     PIC X(40).
          05 STATUS-CODE       PIC X.
             88 STATUS-ACTIVE    VALUE "A".
             88 STATUS-INACTIVE  VALUE "I".
          05 PHONE-NUMBERS OCCURS 3 TIMES.
             10 PHONE-TYPE     PIC X(2).
             10 PHONE-NUMBER   PIC X(15).
```

## Response copybook

```cobol
       01 CUSTOMER-RESPONSE.
          05 CUSTOMER-ID       PIC 9(9).
          05 CUSTOMER-NAME     PIC X(40).
          05 BALANCE           PIC S9(9)V99 COMP-3.
          05 ITEM-COUNT        PIC 9(3).
          05 ITEMS OCCURS 0 TO 50 TIMES DEPENDING ON ITEM-COUNT.
             10 ITEM-ID        PIC X(10).
             10 ITEM-AMOUNT    PIC S9(7)V99.
```

## API specification

```json
{
  "api": {
    "title": "Customer API",
    "version": "1.0.0",
    "description": "Customer lookup.",
    "contextRoot": "/api/customer",
    "host": "example.com",
    "schemes": ["https"]
  },
  "operation": {
    "path": "/customers/{customerId}",
    "method": "get",
    "operationId": "getCustomer",
    "summary": "Get a customer",
    "tags": ["customers"]
  },
  "parameters": [
    {
      "name": "customerId",
      "in": "path",
      "required": true,
      "type": "integer",
      "format": "int64"
    }
  ],
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
      {"field": "ITEM-COUNT", "reason": "ODO counter computed from the array."}
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
    "dir": "zosconnect-contract"
  }
}
```

## Swagger 2.0 fragment

```json
{
  "swagger": "2.0",
  "info": {"title": "Customer API", "version": "1.0.0"},
  "host": "example.com",
  "basePath": "/api/customer",
  "schemes": ["https"],
  "paths": {
    "/customers/{customerId}": {
      "get": {
        "operationId": "getCustomer",
        "parameters": [
          {
            "name": "customerId",
            "in": "path",
            "required": true,
            "type": "integer",
            "format": "int64"
          }
        ],
        "responses": {
          "200": {
            "description": "Customer found",
            "schema": {"$ref": "#/definitions/CustomerResponse"}
          },
          "404": {
            "description": "Customer not found",
            "schema": {"$ref": "#/definitions/ErrorResponse"}
          }
        }
      }
    }
  },
  "definitions": {
    "CustomerResponse": {
      "type": "object",
      "required": ["customerId"],
      "properties": {
        "customerId": {"type": "integer", "format": "int64"},
        "customerName": {"type": "string", "maxLength": 40},
        "balance": {"type": "number", "format": "decimal"},
        "items": {
          "type": "array",
          "minItems": 0,
          "maxItems": 50,
          "items": {
            "type": "object",
            "properties": {
              "itemId": {"type": "string", "maxLength": 10},
              "itemAmount": {"type": "number", "format": "decimal"}
            }
          }
        }
      }
    }
  }
}
```

## OpenAPI 3.0 fragment

```yaml
openapi: 3.0.3
info:
  title: Customer API
  version: 1.0.0
servers:
  - url: https://example.com/api/customer
paths:
  /customers/{customerId}:
    get:
      operationId: getCustomer
      summary: Get a customer
      parameters:
        - name: customerId
          in: path
          required: true
          schema:
            type: integer
            format: int64
      responses:
        "200":
          description: Customer found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CustomerResponse'
        "404":
          description: Customer not found
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
components:
  schemas:
    CustomerResponse:
      type: object
      required:
        - customerId
      properties:
        customerId:
          type: integer
          format: int64
        customerName:
          type: string
          maxLength: 40
        balance:
          type: number
          format: decimal
        items:
          type: array
          minItems: 0
          maxItems: 50
          items:
            type: object
            properties:
              itemId:
                type: string
                maxLength: 10
              itemAmount:
                type: number
                format: decimal
```

## mapping-analysis.md fragment

```markdown
| COBOL field | JSON path | JSON type | Required | Evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| CUSTOMER-ID | customerId | integer/int64 | yes | Interface contract | mapped | |
| CUSTOMER-NAME | customerName | string(40) | no | - | mapped | |
| BALANCE | balance | number/decimal | no | COMP-3 | mapped | |
| ITEM-COUNT | - | - | no | ODO counter | excluded | Computed from ITEMS. |
| ITEMS | items | array(0..50) | no | OCCURS DEPENDING ON | mapped | Confirm runtime cardinality. |
| STATUS-CODE | - | - | no | Level 88 not confirmed as enum | needs-review | Confirm enum values. |
```

## Rejected examples

These contracts must fail validation:

- `openapi: 3.1.0` — z/OS Connect 3.0 does not support OpenAPI 3.1.
- `responses: {"2XX": ...}` — response ranges are not supported.
- `$ref: "https://example.com/schema.json"` — remote references are not
  supported.
- `head` or `trace` operations — not supported.
- `type: null` — use `nullable` only with an explicit type.
- `required: ["missing"]` when `missing` is not in `properties`.
- `type: array` without `items`.
- `allOf` with a sibling `properties` block.
- Duplicate `operationId` values.
- A path parameter that is not declared in the path template.
- Swagger 2.0 and OpenAPI 3.0 with different paths or operation IDs.
