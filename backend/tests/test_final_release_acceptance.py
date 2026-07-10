import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _local_markdown_targets(markdown_path: Path) -> list[Path]:
    text = markdown_path.read_text(encoding="utf-8")
    targets: list[Path] = []
    for match in re.finditer(r"!?\[[^\]]*]\(([^)]+)\)", text):
        raw_target = match.group(1).strip()
        if raw_target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = raw_target.split()[0].strip("\"'")
        target = target.split("#", 1)[0]
        if not target:
            continue
        targets.append((markdown_path.parent / target).resolve())
    return targets


def test_final_acceptance_report_exists_and_documents_release_quality():
    report = ROOT / "docs" / "final_acceptance_report.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    for phrase in [
        "最终验收报告",
        "AI 应用开发作品集",
        "功能验收",
        "工程验收",
        "发布前验证",
        "不进入 GitHub",
        "生产化边界",
    ]:
        assert phrase in text


def test_public_docs_link_final_acceptance_report():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "github_release_checklist.md").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "prepare_github_release.ps1").read_text(encoding="utf-8")
    assert "docs/final_acceptance_report.md" in readme
    assert "docs/final_acceptance_report.md" in checklist
    assert "docs/final_acceptance_report.md" in script


def test_public_markdown_local_links_resolve():
    public_docs = [
        ROOT / "README.md",
        ROOT / "docs" / "github_release_checklist.md",
        ROOT / "docs" / "production_roadmap.md",
        ROOT / "docs" / "interview_talking_points.md",
        ROOT / "docs" / "final_acceptance_report.md",
    ]
    missing = []
    for markdown_path in public_docs:
        assert markdown_path.exists()
        for target in _local_markdown_targets(markdown_path):
            if not target.exists():
                missing.append(f"{markdown_path.relative_to(ROOT)} -> {target.relative_to(ROOT)}")
    assert missing == []


def test_release_scope_excludes_graduation_and_internal_artifacts():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "github_release_checklist.md").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "prepare_github_release.ps1").read_text(encoding="utf-8")

    for pattern in [
        "docs/superpowers/",
        "docs/opening_report.md",
        "docs/thesis_outline.md",
        "docs/hieu_thesis_revision_rules.md",
        "docs/demo_script.md",
    ]:
        assert pattern in gitignore
        assert pattern in checklist
        assert pattern in script

    publish_command = next(line for line in checklist.splitlines() if line.strip().startswith("git add "))
    for required in ["README.md", ".gitignore", ".gitattributes", ".env.example", "backend", "frontend", "samples"]:
        assert required in publish_command
    assert " docs " not in checklist
    assert "Markdown local links" in script
    assert "$MarkdownFilesToValidate" in script
