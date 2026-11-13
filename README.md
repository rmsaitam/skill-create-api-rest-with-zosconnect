# COBOL OpenAPI Generator for z/OS Connect

[![skills.sh](https://skills.sh/b/rmsaitam/skill-create-api-rest-with-zosconnect)](https://skills.sh/rmsaitam/skill-create-api-rest-with-zosconnect)

A plugin and skill that turns COBOL copybooks and a short API interview into
reviewable Swagger 2.0 and OpenAPI 3.0 contracts for z/OS Connect. The
generator never edits a copybook, never invents required fields, and marks
ambiguous constructs as `needs-review` instead of guessing.

## Supported agents

| Agent | Manifest |
| --- | --- |
| Claude Code | `.claude-plugin/plugin.json` |
| Codex | `.codex-plugin/plugin.json` |
| Cursor | `.cursor-plugin/plugin.json` |
| GitHub Copilot CLI | `.github/plugin/marketplace.json` |
| Antigravity | `plugin.json` |
| skills.sh / generic Agent Skills | `skills/cobol-openapi-generator/SKILL.md` |

All agents use the same skill and validation contract. The commands are
`/generate`, `/validate`, and `/analyze`.

## Install

### skills.sh

The recommended installation path is the open Agent Skills CLI. It discovers
`skills/cobol-openapi-generator/SKILL.md` in this repository and installs it for
the agents you select. Node.js 22.20 or newer is required.

```bash
npx skills@1.8.1 add rmsaitam/skill-create-api-rest-with-zosconnect
npx skills@1.8.1 add rmsaitam/skill-create-api-rest-with-zosconnect -g -y
```

Use `-g` for a global install and `-y` to skip prompts. To list the skills
available in this repository without installing:

```bash
npx skills@1.8.1 add rmsaitam/skill-create-api-rest-with-zosconnect --list
```

To install only this skill for a specific agent:

```bash
npx skills@1.8.1 add rmsaitam/skill-create-api-rest-with-zosconnect \
  --skill cobol-openapi-generator -a claude-code
```

### Claude Code

Add the marketplace and install the plugin:

```bash
/plugin marketplace add rmsaitam/skill-create-api-rest-with-zosconnect
/plugin install create-api-rest-with-zosconnect
```

### Codex

Point the Codex marketplace at this repository and install
`create-api-rest-with-zosconnect`.

### Cursor, Copilot CLI, and Antigravity

Use the plugin marketplace manifests in `.cursor-plugin/`, `.github/plugin/`,
`.agents/plugins/`, or `plugin.json`, or install through `skills.sh`.

### Manual copy

Copy the skill directory directly:

```bash
mkdir -p ~/.agents/skills
cp -R skills/cobol-openapi-generator ~/.agents/skills/cobol-openapi-generator
```

Confirm the package before installing:

```bash
python3 scripts/validate_plugin.py .
```

## Workflow

1. Collect the API details with `references/question-bank.md`.
2. Parse copybooks with `scripts/copybook_parser.py`.
3. Record every mapping decision in the API specification.
4. Generate contracts with `scripts/generate_contract.py`.
5. Validate the outputs with `scripts/validate_contract.py`.

Generation writes `mapping-analysis.md` and `generation-report.md` next to the
contracts. The report lists toolchain steps and `needs-review` items.

## Requirements

- Python 3.10 or later.
- PyYAML 6.0 or later for OpenAPI YAML output.
- Node.js 22.20 or newer for installation through `skills.sh`.
- The target z/OS Connect Designer, Gradle plug-in, or `zconbt` for runtime
  import and build verification.

Runtime compatibility is never claimed from static validation alone. Import or
build the contract with the target z/OS Connect toolchain before deployment.

## Commands

```bash
python3 skills/cobol-openapi-generator/scripts/copybook_parser.py copybook.cbl --json
python3 skills/cobol-openapi-generator/scripts/generate_contract.py --spec api-spec.json --out build
python3 skills/cobol-openapi-generator/scripts/validate_contract.py \
  --swagger build/swagger.json \
  --openapi build/openapi.yml \
  --mapping build/mapping-analysis.md \
  --context-root /api/customer
```

## Safety Rules

- Copybooks are read-only inputs.
- A field is `required` only with explicit evidence.
- `REDEFINES`, `OCCURS DEPENDING ON` counters, and level-88 conditions require
  review.
- Response ranges, `HEAD`, `TRACE`, external references, and OpenAPI 3.1 are
  rejected.
- Output paths may not escape the output directory or overwrite an input.

## Development

```bash
make setup
make check
```

`make test` runs the suite, `make coverage` enforces at least 80 percent line
coverage, `make validate` checks the plugin structure, and `make security` runs
Bandit.

## License

MIT. See `LICENSE`.

## Security

Report vulnerabilities as described in `SECURITY.md`. Do not include customer
copybooks, credentials, or production data in public reports.
