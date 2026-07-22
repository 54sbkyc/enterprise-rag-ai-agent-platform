from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_github_actions_pytest_workflow_exists():
    workflow = ROOT / ".github" / "workflows" / "tests.yml"
    assert workflow.exists()
    text = workflow.read_text(encoding="utf-8")
    for phrase in [
        "name: Tests",
        "actions/checkout@v5",
        "actions/setup-python@v6",
        'python-version: "3.12"',
        "python -m pip install -r requirements.txt",
        "python check_requirements.py",
        "python -m pytest",
        "python -m app.eval_gate_cli",
        "actions/upload-artifact@v4",
        "working-directory: backend",
    ]:
        assert phrase.lower() in text.lower()


def test_production_roadmap_explains_upgrade_path():
    roadmap = ROOT / "docs" / "production_roadmap.md"
    assert roadmap.exists()
    text = roadmap.read_text(encoding="utf-8")
    for phrase in [
        "生产化路线图",
        "embedding",
        "pgvector",
        "rerank",
        "PostgreSQL",
        "异步 Agent",
        "部门级 ACL",
        "观测与成本治理",
    ]:
        assert phrase.lower() in text.lower()


def test_readme_and_release_checklist_link_ci_and_roadmap():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "github_release_checklist.md").read_text(encoding="utf-8")
    assert ".github/workflows/tests.yml" in readme
    assert "docs/production_roadmap.md" in readme
    assert "docs/rag_quality_gate.md" in readme
    assert ".github/workflows/tests.yml" in checklist
    assert "docs/production_roadmap.md" in checklist
    assert "docs/rag_quality_gate.md" in checklist


def test_release_audit_requires_ci_and_roadmap():
    script = (ROOT / "scripts" / "prepare_github_release.ps1").read_text(encoding="utf-8")
    assert ".github/workflows/tests.yml" in script
    assert "docs/production_roadmap.md" in script
    assert "docs/rag_quality_gate.md" in script
