from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_frontend_lists_default_to_five_items_per_page():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert script.count("pageSize: 5") >= 12
    assert "page-size-select" not in script
    assert "data-page-size" not in script
    assert "每页 5 条" in script
    assert 'setText("#logCount", result.total)' in script


def test_clear_record_button_is_a_single_line_text_button():
    stylesheet = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert ".wide-delete-btn" in stylesheet
    assert "white-space: nowrap" in stylesheet
    assert ".toolbar-actions" in stylesheet


def test_question_workspace_permission_is_locked_for_all_roles():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'if (code === "qa.use") return true;' in script


def test_remember_login_does_not_store_plaintext_password():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "saved.password" not in script
    assert "JSON.stringify({ remember: true, username, password })" not in script
    assert '"password" in saved' in script
    assert "记住账号" in markup


def test_employee_permission_column_is_visual_only():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'const visualOnly = role === "employee";' in script
    assert 'data-visual-only="${visualOnly ? "true" : ""}"' in script
    assert '.filter((input) => input.checked && input.dataset.visualOnly !== "true")' in script
    assert 'const displayedChecked = visualOnly ? permission.code === "qa.use" : checked;' in script
    assert '<span>${visualOnly ? "锁定"' in script
    assert ".permission-cell.employee-visual" not in stylesheet


def test_removed_legacy_frontend_markup_and_styles_do_not_return():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert ".page-size-select" not in stylesheet
    assert "page-audit-legacy" not in markup
    assert "clearAuditBtnLegacy" not in markup
    assert '<option value="closed">无需处理</option>' in markup
    assert "log-answer-preview" in script
    assert ".log-answer-preview" in stylesheet


def test_fastapi_uses_lifespan_instead_of_deprecated_startup_event():
    main = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")

    assert "@app.on_event" not in main
    assert "lifespan=lifespan" in main


def test_project_name_is_unified_across_runtime_and_shell():
    config = (ROOT / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'APP_NAME = "企业知识库问答管理系统"' in config
    assert "<title>企业知识库问答管理系统</title>" in markup
    assert "知识库问答系统" not in markup
    assert "智能企业知识库问答管理系统" not in markup
    assert "Enterprise RAG QA Platform" not in config


def test_login_controls_are_wrapped_in_a_real_form():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert '<form id="loginForm"' in markup
    assert '<button id="loginBtn" class="primary-btn full" type="submit">登录</button>' in markup
    assert '#loginForm' in script
    assert 'event.preventDefault()' in script


def test_page_declares_favicon_to_avoid_browser_404_noise():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert '<link rel="icon"' in markup
    assert 'data:image/svg+xml' in markup


def test_mobile_sidebar_is_collapsible_and_keeps_content_in_first_viewport():
    stylesheet = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="mobileNavToggle"' in markup
    assert 'aria-controls="primaryNav"' in markup
    assert 'id="primaryNav"' in markup
    assert "mobile-nav-collapsed" in markup
    assert ".mobile-nav-toggle" in stylesheet
    assert ".sidebar.mobile-nav-collapsed .nav" in stylesheet
    assert "function setMobileNavExpanded" in script
    assert '$("#mobileNavToggle").addEventListener("click"' in script
    assert 'window.matchMedia("(max-width: 1060px)").matches' in script


def test_health_risk_documents_use_five_item_pagination():
    markup = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'healthDocuments: { page: 1, pageSize: 5, total: 0 }' in script
    assert 'id="healthDocumentPagination"' in markup
    assert 'renderPagination("#healthDocumentPagination", "healthDocuments"' in script
    assert "items.slice(start, start + paging.pageSize)" in script
    assert "不按普通列表" not in markup + script
