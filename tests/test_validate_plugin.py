from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_plugin  # noqa: E402
from validate_plugin import validate_plugin as run_validation  # noqa: E402

IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "*.pyc")


def clone(tmp_path: Path) -> Path:
    destination = tmp_path / "plugin"
    shutil.copytree(ROOT, destination, ignore=IGNORE)
    return destination


def errors(report: validate_plugin.Report) -> set[str]:
    return {item.code for item in report.errors}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: object) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_repository_is_valid() -> None:
    report = run_validation(ROOT)
    assert report.ok, "\n".join(item.message for item in report.errors)
    assert report.stats["version"] == "0.1.0"
    assert not report.warnings


def test_cli_human_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert validate_plugin.main([str(ROOT)]) == 0
    assert "PASS" in capsys.readouterr().out
    assert validate_plugin.main([str(ROOT), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert validate_plugin.main([str(ROOT / "tests/fixtures/contracts")]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_missing_required_file(tmp_path: Path) -> None:
    root = clone(tmp_path)
    (root / "commands/analyze.md").unlink()
    report = run_validation(root)
    assert "missing-file" in errors(report)


def test_missing_required_files_and_empty(tmp_path: Path) -> None:
    root = clone(tmp_path)
    (root / "README.md").write_text("", encoding="utf-8")
    (root / "LICENSE").unlink()
    report = run_validation(root)
    assert "empty-file" in errors(report)
    assert "missing-file" in errors(report)


def test_root_manifest_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    data = load(root / "plugin.json")
    data["version"] = "0.1.0"
    data["$schema"] = "https://example.com/schema.json"
    data["name"] = "wrong"
    save(root / "plugin.json", data)
    report = run_validation(root)
    assert {"root-extra-key", "invalid-schema", "wrong-name"} <= errors(report)


def test_generic_manifest_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    data = load(root / ".codex-plugin/plugin.json")
    data.update(name="wrong", version="9.9.9", description="short", license="Apache")
    data["author"] = {"name": "", "url": "not a url"}
    data["homepage"] = "your-org.example.com"
    save(root / ".codex-plugin/plugin.json", data)
    report = run_validation(root)
    codes = errors(report)
    assert {
        "wrong-name",
        "version-mismatch",
        "invalid-manifest-value",
        "missing-license",
        "invalid-url",
        "placeholder-url",
    } <= codes


def test_author_string_and_missing_values(tmp_path: Path) -> None:
    root = clone(tmp_path)
    data = load(root / ".cursor-plugin/plugin.json")
    data["author"] = ""
    data.pop("description")
    save(root / ".cursor-plugin/plugin.json", data)
    report = run_validation(root)
    assert {"missing-manifest-key", "missing-author"} <= errors(report)


def test_marketplace_common_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    data = load(root / ".cursor-plugin/marketplace.json")
    data["name"] = "wrong"
    data["plugins"] = "bad"
    save(root / ".cursor-plugin/marketplace.json", data)
    report = run_validation(root)
    assert {"wrong-name", "missing-plugins"} <= errors(report)


def test_marketplace_plugin_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    data = load(root / ".claude-plugin/marketplace.json")
    data["plugins"] = [{"name": "wrong", "description": "short", "source": "missing-dir"}]
    save(root / ".claude-plugin/marketplace.json", data)
    report = run_validation(root)
    codes = errors(report)
    assert {"wrong-name", "invalid-manifest-value", "missing-directory"} <= codes


def test_claude_owner_schema_and_plugin_shape(tmp_path: Path) -> None:
    root = clone(tmp_path)
    data = load(root / ".claude-plugin/marketplace.json")
    data.pop("$schema")
    data.pop("owner")
    data["plugins"] = ["bad", {"name": "create-api-rest-with-zosconnect", "source": {"source": "remote", "path": "."}}]
    save(root / ".claude-plugin/marketplace.json", data)
    report = run_validation(root)
    assert {"missing-schema", "missing-owner", "invalid-plugin-entry", "invalid-source"} <= errors(report)


def test_codex_interface_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    path = root / ".codex-plugin/plugin.json"
    data = load(path)
    data["skills"] = "missing"
    interface = data["interface"]
    for key in ("displayName", "shortDescription", "longDescription", "developerName", "category"):
        interface.pop(key)
    interface["websiteURL"] = "bad"
    interface["brandColor"] = "blue"
    interface["composerIcon"] = "missing.svg"
    interface["logo"] = "missing.svg"
    interface["capabilities"] = []
    interface["defaultPrompt"] = []
    interface["screenshots"] = "bad"
    save(path, data)
    report = run_validation(root)
    codes = errors(report)
    assert {
        "missing-directory",
        "missing-asset",
        "invalid-manifest-value",
        "invalid-url",
        "invalid-brand-color",
        "missing-capabilities",
        "missing-prompts",
        "invalid-screenshots",
    } <= codes


def test_codex_missing_interface(tmp_path: Path) -> None:
    root = clone(tmp_path)
    path = root / ".codex-plugin/plugin.json"
    data = load(path)
    data.pop("interface")
    save(path, data)
    report = run_validation(root)
    assert "missing-interface" in errors(report)


def test_cursor_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    plugin = load(root / ".cursor-plugin/plugin.json")
    plugin["skills"] = "missing"
    plugin["commands"] = "missing"
    plugin["logo"] = "missing.svg"
    save(root / ".cursor-plugin/plugin.json", plugin)
    marketplace = load(root / ".cursor-plugin/marketplace.json")
    marketplace.pop("owner")
    marketplace["metadata"] = {}
    marketplace["plugins"] = [{"name": "create-api-rest-with-zosconnect", "description": "x" * 40, "source": 5}]
    save(root / ".cursor-plugin/marketplace.json", marketplace)
    report = run_validation(root)
    assert {"missing-directory", "missing-asset", "missing-owner", "missing-metadata", "missing-source"} <= errors(report)


def test_copilot_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    path = root / ".github/plugin/marketplace.json"
    data = load(path)
    data.pop("owner")
    data["metadata"] = {"version": "9.9.9", "description": "short"}
    data["plugins"] = [
        {
            "name": "create-api-rest-with-zosconnect",
            "description": "x" * 40,
            "version": "9.9.9",
            "source": "missing-dir",
        }
    ]
    save(path, data)
    report = run_validation(root)
    assert {"missing-owner", "version-mismatch", "invalid-manifest-value", "missing-directory"} <= errors(report)
    data.pop("metadata")
    save(path, data)
    report = run_validation(root)
    assert "missing-metadata" in errors(report)


def test_agents_marketplace_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    path = root / ".agents/plugins/marketplace.json"
    data = load(path)
    data.pop("interface")
    plugin = data["plugins"][0]
    plugin["source"] = "../escape"
    plugin["policy"] = {"installation": "NO", "authentication": "NO"}
    plugin.pop("category")
    save(path, data)
    report = run_validation(root)
    assert {"missing-interface", "path-escape", "invalid-policy", "invalid-manifest-value"} <= errors(report)
    plugin.pop("policy")
    save(path, data)
    report = run_validation(root)
    assert "missing-policy" in errors(report)


def test_skill_frontmatter_and_content(tmp_path: Path) -> None:
    root = clone(tmp_path)
    skill = root / "skills/cobol-openapi-generator/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    skill.write_text("plain text\n", encoding="utf-8")
    report = run_validation(root)
    assert "missing-frontmatter" in errors(report)
    skill.write_text(text.replace("name: cobol-openapi-generator", "name: wrong"), encoding="utf-8")
    report = run_validation(root)
    assert "wrong-name" in errors(report)
    skill.write_text(text.replace("license: MIT", "license: Apache"), encoding="utf-8")
    report = run_validation(root)
    assert "missing-license" in errors(report)
    skill.write_text(text.replace('  version: "0.1.0"', '  version: "9.9.9"'), encoding="utf-8")
    report = run_validation(root)
    assert "version-mismatch" in errors(report)
    skill.write_text(text.replace("  author: Reginaldo (rmsaitam)\n", ""), encoding="utf-8")
    report = run_validation(root)
    assert "missing-author" in errors(report)
    short = "\n".join("description: short" if line.startswith("description:") else line for line in text.splitlines()) + "\n"
    skill.write_text(short, encoding="utf-8")
    report = run_validation(root)
    assert "weak-description" in errors(report)


def test_skill_reference_and_terms(tmp_path: Path) -> None:
    root = clone(tmp_path)
    skill = root / "skills/cobol-openapi-generator/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    skill.write_text(text + "\n[missing](references/missing.md)\n", encoding="utf-8")
    report = run_validation(root)
    assert "missing-reference" in errors(report)
    skill.write_text(text.replace("contextRoot", "context root"), encoding="utf-8")
    report = run_validation(root)
    assert "missing-skill-content" in errors(report)


def test_openai_yaml_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    path = root / "agents/openai.yaml"
    path.write_text('interface:\n  short_description: "x"\n  default_prompt: "no skill"\n', encoding="utf-8")
    report = run_validation(root)
    assert {"missing-openai-field", "missing-skill-invocation"} <= errors(report)


def test_svg_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    (root / "assets/icon.svg").write_text("not xml", encoding="utf-8")
    (root / "assets/logo.svg").write_text('<?xml version="1.0"?><!DOCTYPE svg><svg/>', encoding="utf-8")
    report = run_validation(root)
    assert "invalid-svg" in errors(report)
    (root / "assets/icon.svg").write_text("<foo/>", encoding="utf-8")
    (root / "assets/logo.svg").write_text("<svg>" + ("x" * (1024 * 1024)) + "</svg>", encoding="utf-8")
    report = run_validation(root)
    assert "invalid-svg" in errors(report)


def test_command_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    generate = root / "commands/generate.md"
    text = generate.read_text(encoding="utf-8")
    generate.write_text("no frontmatter", encoding="utf-8")
    report = run_validation(root)
    assert "missing-frontmatter" in errors(report)
    generate.write_text(text.replace("argument-hint:", "hint:"), encoding="utf-8")
    report = run_validation(root)
    assert "missing-argument-hint" in errors(report)
    generate.write_text(text.replace("generate_contract.py", "generator"), encoding="utf-8")
    report = run_validation(root)
    assert "missing-command-content" in errors(report)
    analyze = root / "commands/analyze.md"
    analyze.write_text(analyze.read_text(encoding="utf-8").replace("description:", "summary:"), encoding="utf-8")
    report = run_validation(root)
    assert "weak-description" in errors(report)


def test_documentation_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    (root / "README.md").write_text("# Nothing\n", encoding="utf-8")
    (root / "SECURITY.md").write_text("# Nothing\n", encoding="utf-8")
    (root / "LICENSE").write_text("Apache License\n", encoding="utf-8")
    (root / "Makefile").write_text("all:\n\ttrue\n", encoding="utf-8")
    (root / ".github/workflows/ci.yml").write_text("name: CI\n", encoding="utf-8")
    (root / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    report = run_validation(root)
    assert {
        "missing-readme-content",
        "missing-security-content",
        "invalid-license",
        "missing-make-target",
        "missing-ci-step",
        "missing-gitignore",
    } <= errors(report)


def test_skills_lock_errors(tmp_path: Path) -> None:
    root = clone(tmp_path)
    path = root / "skills-lock.json"
    data = load(path)
    data["version"] = 2
    save(path, data)
    report = run_validation(root)
    assert "invalid-skills-lock" in errors(report)
    data["version"] = 1
    data["skills"] = {}
    save(path, data)
    report = run_validation(root)
    assert "missing-skills-lock-entry" in errors(report)
    data["skills"] = {"cobol-openapi-generator": "bad"}
    save(path, data)
    report = run_validation(root)
    assert "invalid-skills-lock-entry" in errors(report)
    data["skills"] = {
        "cobol-openapi-generator": {
            "source": "other/repo",
            "sourceType": "git",
            "skillPath": "wrong",
            "computedHash": "bad",
        }
    }
    save(path, data)
    report = run_validation(root)
    codes = errors(report)
    assert "invalid-skills-lock-entry" in codes
    assert "skills-lock-hash" in codes


def test_placeholders_and_code_blocks(tmp_path: Path) -> None:
    root = clone(tmp_path)
    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8")
    readme.write_text(text + '\n```text\nTODO\n```\n\n`TODO`\n\n<!-- TODO -->\n', encoding="utf-8")
    report = run_validation(root)
    assert "placeholder" not in errors(report)
    readme.write_text(text + "\nTODO\n", encoding="utf-8")
    report = run_validation(root)
    assert "placeholder" in errors(report)


def test_invalid_and_duplicate_json(tmp_path: Path) -> None:
    root = clone(tmp_path)
    (root / "plugin.json").write_text('{"name": "a", "name": "b"}', encoding="utf-8")
    report = run_validation(root)
    assert "duplicate-json-key" in errors(report)
    (root / "plugin.json").write_text("{", encoding="utf-8")
    report = run_validation(root)
    assert "invalid-json" in errors(report)


def test_unreadable_text_and_json_shape(tmp_path: Path) -> None:
    root = clone(tmp_path)
    (root / "plugin.json").write_text("[]", encoding="utf-8")
    report = run_validation(root)
    assert "invalid-json-root" in errors(report)
