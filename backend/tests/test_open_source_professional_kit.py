import re
from pathlib import Path

from app.config import APP_VERSION


ROOT = Path(__file__).resolve().parents[2]


def _local_links(markdown_path: Path) -> list[Path]:
    text = markdown_path.read_text(encoding="utf-8")
    links: list[Path] = []
    for match in re.finditer(r"!?\[[^\]]*]\(([^)]+)\)", text):
        raw_target = match.group(1).strip()
        if raw_target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = raw_target.split()[0].strip("\"'")
        target = target.split("#", 1)[0]
        if target:
            links.append((markdown_path.parent / target).resolve())
    return links


def test_security_policy_documents_ai_application_boundaries():
    doc = ROOT / "SECURITY.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "安全说明",
        "不要提交真实密钥",
        "本地运行数据",
        "Prompt 注入",
        "权限控制",
        "漏洞反馈",
        "AI 安全边界",
    ]:
        assert phrase in text


def test_contributing_guide_documents_repeatable_workflow():
    doc = ROOT / "CONTRIBUTING.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "贡献指南",
        "快速启动",
        "运行测试",
        "发布检查",
        "文档同步",
        "不要提交",
        "python -m pytest",
        "python -m app.eval_gate_cli",
    ]:
        assert phrase in text


def test_architecture_decisions_explain_key_tradeoffs():
    doc = ROOT / "docs" / "architecture_decisions.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "架构决策记录",
        "FastAPI",
        "SQLite",
        "BM25",
        "Embedding",
        "Agent 工具调用",
        "本地抽取式回答",
        "OpenAI Chat Completions",
        "发布治理",
        "RAG 回归门禁",
    ]:
        assert phrase in text


def test_professional_docs_are_linked_from_release_materials():
    required_paths = [
        "SECURITY.md",
        "CONTRIBUTING.md",
        "docs/architecture_decisions.md",
    ]
    materials = {
        "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
        "docs/github_release_checklist.md": (ROOT / "docs" / "github_release_checklist.md").read_text(encoding="utf-8"),
        "docs/final_acceptance_report.md": (ROOT / "docs" / "final_acceptance_report.md").read_text(encoding="utf-8"),
        "scripts/prepare_github_release.ps1": (ROOT / "scripts" / "prepare_github_release.ps1").read_text(encoding="utf-8"),
    }
    for name, text in materials.items():
        for required_path in required_paths:
            assert required_path in text, f"{name} should reference {required_path}"


def test_professional_markdown_links_resolve():
    docs = [
        ROOT / "SECURITY.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "docs" / "architecture_decisions.md",
    ]
    missing = []
    for doc in docs:
        assert doc.exists()
        for link in _local_links(doc):
            if not link.exists():
                missing.append(f"{doc.relative_to(ROOT)} -> {link.relative_to(ROOT)}")
    assert missing == []


def test_repository_has_mit_license_linked_from_public_materials():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "github_release_checklist.md").read_text(encoding="utf-8")

    assert license_text.startswith("MIT License")
    assert "Copyright (c) 2026 54sbkyc" in license_text
    assert "LICENSE" in readme
    assert "LICENSE" in checklist


def test_public_release_notes_match_application_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_path = ROOT / "docs" / "releases" / f"v{APP_VERSION}.md"
    release_notes = release_path.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"## [{APP_VERSION}] - 2026-07-27" in changelog
    assert "161 项 pytest" in changelog
    assert release_notes.startswith(f"# v{APP_VERSION} - ")
    assert "Resilient Model Gateway Release" in release_notes
    assert f"docs/releases/v{APP_VERSION}.md" in readme
    assert "CHANGELOG.md" in readme
