# COBOL copybook guide

This reference explains the copybook constructs the parser understands and the
ones that require a human decision. It is not a COBOL language manual.

## Source format

### Fixed format

The default parser expects the traditional fixed format:

| Columns | Content |
| --- | --- |
| 1-6 | Sequence number, usually blank |
| 7 | Indicator: `*` or `/` is a comment, `D` is debug, `-` is continuation |
| 8-72 | COBOL source text |
| 73-80 | Identification area, ignored |

Comments and blank lines are ignored. A line whose column 7 is `*`, `/`, or `D`
is not treated as source. A continuation line joins the previous statement.

### Free format

Use `--free-format` for free-form copybooks. In free format, `*>` starts a
comment and statements end with a period followed by whitespace or end of file.

### Statement boundaries

A copybook entry normally ends with a period. Periods inside `PIC` clauses, such
as `PIC 9.99`, are part of the picture and must not end the statement. The parser
uses the statement terminator only when it is followed by whitespace and the
next entry or by end of file.

## Levels

| Level | Meaning | Mapping guidance |
| --- | --- | --- |
| `01` | Root record | Top-level object or array item |
| `02`-`49` | Group or elementary item | Object or property |
| `66` | Renames | Requires review; do not auto-map |
| `77` | Independent elementary item | Property at the root or excluded |
| `88` | Condition name | Enum only with explicit evidence |
| `78` | Constant | Excluded from the payload |

A group item has children. An elementary item has a `PIC` clause. A level-88
entry is attached to the preceding elementary or group item.

## PICTURE clauses

Common picture symbols:

| Symbol | Meaning |
| --- | --- |
| `9` | Digit |
| `X` | Alphanumeric character |
| `A` | Alphabetic character |
| `N` | National (DBCS) character |
| `G` | Graphic (DBCS) character |
| `S` | Signed |
| `V` | Implied decimal point |
| `P` | Assumed decimal scaling position |
| `Z` | Zero-suppressed digit |
| `.` | Explicit decimal point |
| `,` | Editing comma |
| `+` / `-` | Editing sign |
| `CR` / `DB` | Credit/debit editing |
| `$` | Currency symbol |

Examples:

```cobol
05 CUSTOMER-NAME       PIC X(40).
05 CUSTOMER-ID         PIC 9(9).
05 BALANCE             PIC S9(9)V99.
05 RATE                PIC 9(3)V9(4).
05 FLAG                PIC X.
05 AMOUNT-EDITED       PIC Z(7)9.99.
```

## USAGE clauses

| USAGE | Typical JSON mapping | Notes |
| --- | --- | --- |
| `DISPLAY` (default) | `string` or `integer` | Numeric display fields may be integers if ranges allow |
| `COMP`, `COMP-4`, `BINARY` | `integer` or `number`/`decimal` | Sizes depend on `PIC` digits and compiler options |
| `COMP-5` | `integer` or `number`/`decimal` | Native binary; range depends on the picture |
| `COMP-1` | `number`/`float` | Single precision |
| `COMP-2` | `number`/`double` | Double precision |
| `COMP-3`, `PACKED-DECIMAL` | `number`/`decimal` | Packed decimal |
| `DISPLAY-1`, `NATIONAL` | `string` | DBCS; length and encoding require review |
| `POINTER` | none | No direct JSON representation |
| `INDEX` | none | No direct JSON representation |

`SIGN LEADING`, `SIGN TRAILING`, and `SIGN SEPARATE` change the physical length
and representation. They do not change the JSON number semantics, but they must
be recorded when lengths are used.

## OCCURS

Fixed array:

```cobol
05 PHONE-NUMBERS OCCURS 5 TIMES.
   10 PHONE-TYPE      PIC X(2).
   10 PHONE-NUMBER    PIC X(15).
```

Maps to an array with `minItems = maxItems = 5`.

Nested arrays:

```cobol
05 ORDERS OCCURS 10 TIMES.
   10 ORDER-ID        PIC 9(8).
   10 ITEMS OCCURS 20 TIMES.
      15 ITEM-ID      PIC X(10).
```

Only the immediate parent array fields are available when mapping array items in
z/OS Connect. Record nested arrays as `needs-review` unless the target toolchain
confirms support.

## OCCURS DEPENDING ON

```cobol
05 ITEM-COUNT          PIC 9(3).
05 ITEMS OCCURS 0 TO 50 TIMES DEPENDING ON ITEM-COUNT.
   10 ITEM-ID          PIC X(10).
```

Rules:

- The ODO subject and the ODO object must exist in the same structure.
- The counter is computed for input and is not returned as a business field on
  output.
- Use `minItems = 0` and `maxItems = 50` for the array.
- Do not expose the counter unless the developer explicitly requires it. If they
  do, document why and validate with the target toolchain.

## REDEFINES

```cobol
05 PAYMENT-DATA.
   10 CARD-NUMBER      PIC X(19).
05 PAYMENT-DATA-R REDEFINES PAYMENT-DATA.
   10 BANK-ACCOUNT     PIC X(19).
```

`REDEFINES` means two or more views of the same storage. It is not a JSON union
that can be generated safely. The parser marks it as ambiguous; the developer
must choose one view, a `oneOf` with an explicit discriminator, or an exclusion.
Never guess.

## COPY

```cobol
01 CUSTOMER-REQUEST.
   COPY CUSTKEY.
   05 CUSTOMER-NAME    PIC X(40).
```

The parser resolves `COPY` members from the directories passed with
`--copybook-path`. It detects missing members and cycles. The source location of
an inlined member is preserved in diagnostics.

Unresolved `COPY` members are an error: do not generate a partial contract and
pretend the structure is complete.

## Level 88

```cobol
05 STATUS-CODE          PIC X.
   88 STATUS-ACTIVE     VALUE "A".
   88 STATUS-INACTIVE   VALUE "I".
```

Level-88 names are condition names, not stored fields. They can become an `enum`
only when the developer explicitly asks for it and the values are known. Do not
create an `enum` by guessing.

## FILLER and technical fields

`FILLER` fields exist for alignment and padding. They are excluded by default.
Control fields, length prefixes, and generated counters are excluded unless the
developer explicitly requires them. Record every exclusion in
`mapping-analysis.md`.

## Numeric precision

For binary and packed fields, the JSON type depends on the value range and the
target toolchain:

- small digit counts usually fit `integer`/`int32`;
- large digit counts may require `integer`/`int64` or `number`/`decimal`;
- packed decimals use `number`/`decimal`;
- floating point uses `number`/`float` or `number`/`double`.

Record the choice and the evidence. Do not silently widen or narrow a field.

## CICS, IMS, and Db2

- CICS `COMMAREA` and containers may wrap the request/response copybooks.
- IMS message segments and large data structures may contain `LL`, `ZZ`, and
  transaction-code prefixes.
- Db2 includes may contain host variables and SQL structures.
- `EXEC SQL`, `EXEC CICS`, and `EXEC DLI` blocks are not plain copybook entries;
  mark them for review.

The generator handles the data structures; it does not generate service
definitions or transaction code.
