import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_ai_application_demo_runbook_is_publishable_and_linked():
    runbook = ROOT / "docs" / "demo_runbook.md"
    assert runbook.exists()
    text = runbook.read_text(encoding="utf-8")
    for phrase in (
        "AI 应用开发演示脚本",
        "管理员账号",
        "问答可观测",
        "Agent 工作台",
        "评测中心",
        "生产化追问",
    ):
        assert phrase in text

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "github_release_checklist.md").read_text(encoding="utf-8")
    assert "docs/demo_runbook.md" in readme
    assert "docs/demo_runbook.md" in checklist


def test_release_checker_requires_demo_and_scans_secret_patterns():
    script = (ROOT / "scripts" / "prepare_github_release.ps1").read_text(encoding="utf-8")

    assert '"docs/demo_runbook.md"' in script
    assert "Secret pattern scan" in script
    assert "$SecretPatterns" in script
    assert "$SecretFindings" in script
    for label in (
        "OpenAI-style API key",
        "AWS access key",
        "GitHub personal access token",
        "Private key",
    ):
        assert label in script
    assert "$SecretFindings.Count -eq 0" in script


def test_public_source_files_do_not_contain_secret_like_values():
    patterns = (
        re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"ghp_[A-Za-z0-9]{30,}"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    paths = [
        *sorted((ROOT / "backend" / "app").glob("*.py")),
        *sorted((ROOT / "frontend").glob("*.*")),
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / ".env.example",
        ROOT / "start.ps1",
    ]
    findings = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}: {pattern.pattern}")
    assert findings == []


def test_one_command_verification_script_is_non_destructive():
    script_path = ROOT / "scripts" / "verify_project.ps1"
    assert script_path.exists()
    script = script_path.read_text(encoding="utf-8")

    assert "python -m compileall" in script
    assert "-m pip check" in script
    assert "-m pytest" in script
    assert "prepare_github_release.ps1" in script
    assert script.count("$LASTEXITCODE -ne 0") >= 4
    assert 'throw "pytest failed with exit code $LASTEXITCODE"' in script
    for destructive in ("Remove-Item", "Move-Item", "Compress-Archive", "git clean", "git reset"):
        assert destructive not in script
