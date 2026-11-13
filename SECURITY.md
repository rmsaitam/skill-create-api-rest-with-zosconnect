# Security policy

## Reporting a vulnerability

Open a private security advisory at
`https://github.com/rmsaitam/skill-create-api-rest-with-zosconnect/security/advisories`
or contact the maintainer through the repository profile. Do not open a public
issue for an unpatched vulnerability.

Include the affected version, a minimal reproduction, and the impact. Remove
secrets, credentials, customer data, and proprietary copybooks from the report.

## Scope

The plugin processes copybooks and API specifications as untrusted text. It
must never execute COBOL, evaluate expressions, fetch remote `$ref` targets, or
write outside the selected output directory. Generated contracts are source
artifacts; they do not prove runtime behavior.

## Handling sensitive data

- Keep credentials and secrets out of copybooks, specifications, and generated
  artifacts.
- Review `mapping-analysis.md` before sharing because field names and evidence
  can reveal internal system details.
- Validate outputs in an isolated build environment and restrict network access
  where required.
