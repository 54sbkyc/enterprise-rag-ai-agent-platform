import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _markdown_links(markdown_path: Path) -> list[Path]:
    text = markdown_path.read_text(encoding="utf-8")
    targets: list[Path] = []
    for match in re.finditer(r"!?\[[^\]]*]\(([^)]+)\)", text):
        raw_target = match.group(1).strip()
        if raw_target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = raw_target.split()[0].strip("\"'")
        target = target.split("#", 1)[0]
        if target:
            targets.append((markdown_path.parent / target).resolve())
    return targets


def test_resume_project_card_is_ready_for_ai_application_interviews():
    doc = ROOT / "docs" / "resume_project_card.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "简历项目卡",
        "企业知识库 RAG + AI Agent 平台",
        "AI 应用开发",
        "FastAPI",
        "RAG",
        "Agent 工具调用",
        "AI 可观测",
        "自动化测试",
        "面试 60 秒介绍",
        "诚实边界",
    ]:
        assert phrase in text


def test_portfolio_scorecard_explains_interviewer_value():
    doc = ROOT / "docs" / "portfolio_review_scorecard.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "面试官评分卡",
        "AI 应用能力",
        "后端工程能力",
        "全栈交付能力",
        "安全与权限意识",
        "可观测与成本意识",
        "测试与交付意识",
        "生产化成熟度",
        "综合判断",
    ]:
        assert phrase in text


def test_showcase_docs_are_linked_from_release_materials():
    expected_links = [
        "docs/resume_project_card.md",
        "docs/portfolio_review_scorecard.md",
    ]
    texts = {
        "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
        "docs/github_release_checklist.md": (ROOT / "docs" / "github_release_checklist.md").read_text(encoding="utf-8"),
        "docs/final_acceptance_report.md": (ROOT / "docs" / "final_acceptance_report.md").read_text(encoding="utf-8"),
        "scripts/prepare_github_release.ps1": (ROOT / "scripts" / "prepare_github_release.ps1").read_text(encoding="utf-8"),
    }
    for path, text in texts.items():
        for link in expected_links:
            assert link in text, f"{path} should reference {link}"


def test_showcase_markdown_links_resolve():
    docs = [
        ROOT / "docs" / "resume_project_card.md",
        ROOT / "docs" / "portfolio_review_scorecard.md",
    ]
    missing = []
    for doc in docs:
        assert doc.exists()
        for target in _markdown_links(doc):
            if not target.exists():
                missing.append(f"{doc.relative_to(ROOT)} -> {target.relative_to(ROOT)}")
    assert missing == []


def test_interview_demo_checklist_covers_preflight_and_failure_modes():
    checklist = ROOT / "docs" / "interview_demo_checklist.md"
    assert checklist.exists()
    text = checklist.read_text(encoding="utf-8")
    for phrase in [
        "面试前五分钟",
        "八分钟主线",
        "火星差旅费用如何报销",
        "Embedding 未配置",
        "LLM 未配置或调用失败",
        "不要这样讲",
    ]:
        assert phrase in text

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    resume = (ROOT / "docs" / "resume_project_card.md").read_text(encoding="utf-8")
    assert "docs/interview_demo_checklist.md" in readme
    assert "interview_demo_checklist.md" in resume
    assert "152 项" in resume
