from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_github_release_checklist_documents_publish_scope():
    checklist = ROOT / "docs" / "github_release_checklist.md"
    assert checklist.exists()
    text = checklist.read_text(encoding="utf-8")
    for phrase in [
        "必须提交",
        "不应提交",
        "发布前检查",
        "backend/data/rag_platform.db",
        "backend/data/uploads/",
        "*.docx",
        "tools/",
    ]:
        assert phrase in text


def test_prepare_github_release_script_is_non_destructive():
    script = ROOT / "scripts" / "prepare_github_release.ps1"
    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "No files will be modified" in text
    assert "Remove-Item" not in text
    assert "Move-Item" not in text
    assert "Compress-Archive" not in text
    for token in ["$RequiredPaths", "$BlockedPaths", "$IgnoredPatterns", "github_release_checklist.md"]:
        assert token in text


def test_gitignore_blocks_local_release_artifacts():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in [
        ".runtime/",
        "*.docx",
        "backend/data/*.db",
        "backend/data/*.db-wal",
        "backend/data/*.db-shm",
        "backend/data/uploads/",
        "tools/",
        "start_tunnel.ps1",
        "tunnel-url.txt",
        "*.zip",
    ]:
        assert pattern in text


def test_readme_links_release_checklist():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/github_release_checklist.md" in text


def test_gitattributes_normalizes_text_and_marks_binary_assets():
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for rule in ["*.py text eol=lf", "*.md text eol=lf", "*.ps1 text eol=crlf", "*.png binary"]:
        assert rule in text
