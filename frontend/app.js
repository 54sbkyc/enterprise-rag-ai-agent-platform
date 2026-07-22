const state = {
  token: "",
  user: null,
  permissions: new Set(),
  permissionCatalog: [],
  rolePermissions: {},
  selectedFile: null,
  documents: [],
  logs: [],
  evaluations: [],
  evaluationCases: [],
  evaluationDataset: null,
  users: [],
  auditLogs: [],
  agentRuns: [],
  knowledgeGaps: [],
  documentVersions: [],
  knowledgeHealth: null,
  qaFeedbacks: [],
  qualityAssessments: [],
  dashboard: null,
  stats: null,
  analytics: null,
  batchRuns: [],
  sessionHistory: [],
  currentLogId: null,
  selectedDocumentId: null,
  activeAgentRunId: null,
  agentPollGeneration: 0,
  route: "dashboard",
  pages: {
    documents: { page: 1, pageSize: 5, total: 0 },
    users: { page: 1, pageSize: 5, total: 0 },
    quality: { page: 1, pageSize: 5, total: 0 },
    logs: { page: 1, pageSize: 5, total: 0 },
    agentRuns: { page: 1, pageSize: 5, total: 0 },
    evaluations: { page: 1, pageSize: 5, total: 0 },
    cases: { page: 1, pageSize: 5, total: 0 },
    batches: { page: 1, pageSize: 5, total: 0 },
    feedback: { page: 1, pageSize: 5, total: 0 },
    gaps: { page: 1, pageSize: 5, total: 0 },
    healthDocuments: { page: 1, pageSize: 5, total: 0 },
    audit: { page: 1, pageSize: 5, total: 0 },
    chunks: { page: 1, pageSize: 5, total: 0 },
    versions: { page: 1, pageSize: 5, total: 0 },
  },
};

const routes = {
  dashboard: { title: "首页总览", subtitle: "查看系统核心指标、最近问答和评测结果。" },
  qa: { title: "问答工作台", subtitle: "基于已入库文档回答问题，并展示引用来源。" },
  agent: { title: "智能体工作台", subtitle: "执行可追踪的知识检索、缺口创建和日志查询工具调用。" },
  documents: { title: "文档管理", subtitle: "上传企业制度、项目资料和业务文档，建立可检索知识库。" },
  evaluation: { title: "评测中心", subtitle: "用标准关键词和期望来源评估回答质量。" },
  retrieval: { title: "检索调试", subtitle: "直接查看 Top-K 命中片段、相似度分数和权限过滤效果。" },
  gaps: { title: "知识缺口", subtitle: "把低置信度问题沉淀为待补充知识任务，形成知识库治理闭环。" },
  health: { title: "健康体检", subtitle: "自动评估知识库质量、风险文档和治理建议。" },
  feedback: { title: "反馈中心", subtitle: "查看员工对回答的有用性反馈，并跟踪知识补充线索。" },
  users: { title: "用户管理", subtitle: "管理平台账号、角色和启用状态。" },
  roles: { title: "角色权限", subtitle: "配置管理员、技术员工和普通员工的模块访问权与操作权。" },
  audit: { title: "操作审计", subtitle: "记录上传、删除、改密级、用户变更等管理动作。" },
  logs: { title: "操作审计", subtitle: "统一查看问答记录、安全拦截和系统管理操作。" },
};

const adminRoutes = new Set(["users", "audit"]);
const employeeRoutes = new Set(["qa"]);
const managementRoles = new Set(["admin", "tech"]);

const roleLabels = {
  admin: "管理员",
  tech: "技术员工",
  employee: "普通员工",
};

const accessLabels = {
  public: "公开资料",
  internal: "内部资料",
  sensitive: "敏感资料",
};

const routePermissions = {
  dashboard: "health.view",
  qa: "qa.use",
  agent: "qa.use",
  documents: "documents.view",
  evaluation: "evaluation.manage",
  retrieval: "retrieval.debug",
  gaps: "gaps.manage",
  health: "health.view",
  feedback: "feedback.manage",
  users: "users.manage",
  roles: "roles.manage",
  audit: "audit.view",
  logs: "audit.view",
};

const gapStatusLabels = {
  open: "待补充",
  processing: "处理中",
  resolved: "已解决",
  closed: "无需处理",
};

const evaluationMetricLabels = {
  total: "用例覆盖",
  recall_at_k: "Recall@K",
  mrr: "MRR",
  answer_accuracy: "答案正确率",
  abstention_accuracy: "拒答准确率",
};

const REMEMBER_LOGIN_KEY = "enterprise_kb_remember_login";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function hasPermission(code) {
  return !code || state.permissions.has(code);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(data.detail || "请求失败");
  }
  return data;
}

function showLogin() {
  $("#authLoading").classList.add("hidden");
  $("#loginScreen").classList.remove("hidden");
  $("#appShell").classList.add("hidden");
  hydrateRememberedLogin();
}

function showApp() {
  $("#authLoading").classList.add("hidden");
  $("#loginScreen").classList.add("hidden");
  $("#appShell").classList.remove("hidden");
  setMobileNavExpanded(false);
}

function setMobileNavExpanded(expanded) {
  const sidebar = $(".sidebar");
  const toggle = $("#mobileNavToggle");
  if (!sidebar || !toggle) return;
  sidebar.classList.toggle("mobile-nav-collapsed", !expanded);
  toggle.setAttribute("aria-expanded", String(expanded));
  toggle.setAttribute("aria-label", expanded ? "收起导航" : "展开导航");
  toggle.title = expanded ? "收起导航" : "展开导航";
  toggle.textContent = expanded ? "×" : "☰";
}

async function login() {
  const username = $("#loginUsername").value.trim();
  const password = $("#loginPassword").value;
  if (!username || !password) {
    setText("#loginStatus", "请输入账号和密码。");
    return;
  }
  setText("#loginStatus", "正在登录...");
  $("#loginBtn").disabled = true;
  try {
    const result = await api("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ username, password }),
    });
    state.token = result.token;
    state.user = result.user;
    state.permissions = new Set(result.permissions || []);
    saveRememberedLogin(username);
    setText("#loginStatus", "");
    applyUserState();
    showApp();
    await loadInitialData();
  } catch (error) {
    setText("#loginStatus", error.message);
  } finally {
    $("#loginBtn").disabled = false;
  }
}

function hydrateRememberedLogin() {
  const raw = localStorage.getItem(REMEMBER_LOGIN_KEY);
  if (!raw) return;
  try {
    const saved = JSON.parse(raw);
    $("#loginUsername").value = saved.username || "";
    $("#loginPassword").value = "";
    $("#rememberLogin").checked = Boolean(saved.remember);
    if ("password" in saved) {
      localStorage.setItem(
        REMEMBER_LOGIN_KEY,
        JSON.stringify({ remember: Boolean(saved.remember), username: saved.username || "" }),
      );
    }
  } catch {
    localStorage.removeItem(REMEMBER_LOGIN_KEY);
  }
}

function saveRememberedLogin(username) {
  if (!$("#rememberLogin")?.checked) {
    localStorage.removeItem(REMEMBER_LOGIN_KEY);
    return;
  }
  localStorage.setItem(REMEMBER_LOGIN_KEY, JSON.stringify({ remember: true, username }));
}

function showForgotPasswordHint() {
  setText("#loginStatus", "请联系系统管理员重置密码。");
  window.setTimeout(() => setText("#loginStatus", ""), 2200);
}

async function restoreSession() {
  localStorage.removeItem("rag_token");
  state.token = "";
  state.user = null;
  state.permissions = new Set();
  showLogin();
}

async function logoutUser() {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch {
    // Local logout should still proceed even if the server session is already gone.
  }
  state.token = "";
  state.user = null;
  state.permissions = new Set();
  showLogin();
}

function applyUserState() {
  const isManager = managementRoles.has(state.user?.role);
  const isAdmin = state.user?.role === "admin";
  const roleLabel = roleLabels[state.user?.role] || "普通员工";
  setText("#userBadge", `${state.user?.display_name || "用户"} · ${roleLabel}`);
  setText("#adminUserBadge", state.user?.display_name || roleLabel);
  setText("#employeeUserBadge", state.user?.display_name || "普通员工");
  setText("#answerBox", isManager ? "请选择左侧“文档管理”上传资料，或直接基于已导入文档提问。" : "");
  $("#appShell")?.classList.toggle("employee-shell", !isManager);
  $$(".nav-item").forEach((node) => {
    node.classList.toggle("hidden", !hasPermission(node.dataset.permission));
  });
  $(".qa-workspace")?.classList.toggle("employee-qa", !isManager);
  $(".citation-sidebar")?.classList.toggle("hidden", !isManager);
  $(".employee-history")?.classList.toggle("hidden", isManager);
  $("#confidenceBadge")?.classList.toggle("hidden", !isManager);
  $("#adminSession")?.classList.toggle("hidden", !isManager);
  $("#employeeSession")?.classList.toggle("hidden", isManager);
  $$(".admin-only").forEach((node) => node.classList.toggle("hidden", !isAdmin));
  $$(".manager-only").forEach((node) => node.classList.toggle("hidden", !isManager));
  $$(".delete-btn").forEach((node) => node.classList.toggle("hidden", !isManager));
}

async function loadInitialData() {
  await checkHealth();
  if (!hasPermission("health.view")) {
    switchRoute("qa");
    return;
  }
  const loaders = [loadDashboard()];
  if (hasPermission("documents.view")) loaders.push(loadDocuments());
  if (hasPermission("qa.use")) loaders.push(loadAgentRuns());
  if (hasPermission("audit.view")) loaders.push(loadLogs());
  if (hasPermission("evaluation.manage")) loaders.push(loadEvaluations(), loadStats(), loadAnalytics());
  if (hasPermission("users.manage")) loaders.push(loadUsers());
  await Promise.all(loaders);
  switchRoute((location.hash || "#dashboard").replace("#", ""));
}

function switchRoute(route) {
  const requestedRoute = routes[route] ? route : "qa";
  if (state.user && !hasPermission(routePermissions[requestedRoute])) {
    state.route = "qa";
    setText("#securityHint", "当前角色没有访问该模块的权限。");
  } else {
    state.route = requestedRoute;
  }
  location.hash = state.route;
  if (window.matchMedia("(max-width: 1060px)").matches) setMobileNavExpanded(false);
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.route === state.route));
  $$(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${state.route}`));
  setText("#pageTitle", routes[state.route].title);
  setText("#pageSubtitle", routes[state.route].subtitle);

  if (!state.user) return;
  if (state.route === "dashboard") loadDashboard();
  if (state.route === "agent") loadAgentRuns();
  if (state.route === "documents") loadDocuments();
  if (state.route === "logs") {
    loadLogs();
    loadAuditLogs();
  }
  if (state.route === "gaps") loadKnowledgeGaps();
  if (state.route === "health") loadKnowledgeHealth();
  if (state.route === "feedback") loadQaFeedbacks();
  if (state.route === "users" && state.user.role === "admin") loadUsers();
  if (state.route === "roles" && hasPermission("roles.manage")) loadRolePermissions();
  if (state.route === "audit" && state.user.role === "admin") loadAuditLogs();
  if (state.route === "evaluation") refreshEvaluationPage();
}

async function refreshEvaluationPage() {
  await Promise.all([
    loadStats(),
    loadAnalytics(),
    loadQualityAssessments(),
    loadEvaluations(),
    loadBatchRuns(),
    loadEvaluationCases(),
    loadEvaluationDataset(),
  ]);
}

async function loadEvaluationDataset() {
  state.evaluationDataset = await api("/api/evaluation/dataset");
  const badge = $("#evaluationDatasetBadge");
  if (!badge) return;
  badge.textContent = `${state.evaluationDataset.version} · ${state.evaluationDataset.case_count} 条`;
  badge.title = `数据集指纹 ${state.evaluationDataset.fingerprint} · 批准基线 ${state.evaluationDataset.approved_baseline?.version || "未配置"}`;
}

async function loadDashboard() {
  state.dashboard = await api("/api/dashboard");
  const stats = state.dashboard.stats;
  setText("#dashDocs", stats.document_count);
  setText("#dashChunks", stats.chunk_count);
  setText("#dashTodayQa", state.dashboard.today_qa_count || 0);
  setText("#dashLowConfidenceCount", state.dashboard.low_confidence_count || 0);
  setText("#dashGapCount", state.dashboard.open_gap_count || 0);
  setText("#dashUsers", state.dashboard.user_count);
  setText("#dashLlm", stats.llm_enabled ? "已启用" : "本地");
  renderBarChart(
    "#dashAccessChart",
    state.dashboard.analytics.access_distribution.map((item) => ({
      label: accessLabels[item.access_level] || item.access_level,
      value: item.count,
    })),
  );
  renderBarChart(
    "#dashTrendChart",
    state.dashboard.analytics.qa_trend.map((item) => ({ label: item.day.slice(5), value: item.count })),
  );
  renderDashboardAiOps(state.dashboard);
  renderDashboardBatch(state.dashboard.recent_batch_runs[0]);
  renderDashboardLogs(state.dashboard.recent_logs);
  renderDashboardLowConfidence(state.dashboard.low_confidence_logs || []);
  renderDashboardDocuments(state.dashboard.recent_documents || []);
  renderSystemStatus(state.dashboard);
}

function renderDashboardAiOps(dashboard) {
  const stats = dashboard.stats || {};
  const usage = stats.ai_usage || {};
  const agentMetrics = state.dashboard.agent_metrics || {};
  setText("#dashAiRequestCount", `${formatCompactNumber(usage.request_count || 0)} 次问答调用`);
  setText("#dashAiTokens", formatCompactNumber(usage.total_tokens || 0));
  setText("#dashAiCost", `$${Number(usage.estimated_cost_usd || 0).toFixed(6)}`);
  setText("#dashAgentRuns", formatCompactNumber(agentMetrics.run_count || 0));
  setText("#dashToolCalls", formatCompactNumber(agentMetrics.total_tool_calls || 0));

  const list = $("#dashAgentRecentRuns");
  const recentRuns = agentMetrics.recent_runs || [];
  if (!list) return;
  if (!recentRuns.length) {
    list.innerHTML = `<div class="empty">暂无 Agent 运行记录。</div>`;
    return;
  }
  list.innerHTML = recentRuns
    .map(
      (run) => `
        <div class="compact-item">
          <strong>${escapeHtml(run.goal)}</strong>
          <span>${toolStatusLabel(run.status)} · ${run.tool_count || 0} 次工具调用 · ${formatDate(run.created_at)}</span>
        </div>
      `,
    )
    .join("");
}

function renderDashboardBatch(run) {
  $("#dashBatch").innerHTML = run
    ? `
      <span>最近运行：${formatDate(run.created_at)}</span>
      <strong>${percentText(run.avg_score)}</strong>
      <span>平均置信度：${percentText(run.avg_confidence)}</span>
      <span>引用命中率：${percentText(run.citation_hit_rate)}</span>
    `
    : `<span>暂无批量评测。</span>`;
}

function renderDashboardLogs(logs) {
  const list = $("#dashLogs");
  if (!logs.length) {
    list.innerHTML = `<div class="empty">暂无问答记录。</div>`;
    return;
  }
  list.innerHTML = logs
    .map(
      (log) => `
        <div class="compact-item">
          <strong>${escapeHtml(log.question)}</strong>
          <span>${log.blocked ? "已拦截" : confidenceLabel(log.confidence)} · ${formatDate(log.created_at)}</span>
        </div>
      `,
    )
    .join("");
}

function renderDashboardLowConfidence(logs) {
  const list = $("#dashLowConfidence");
  if (!logs.length) {
    list.innerHTML = `<div class="empty">暂无低置信度问题。</div>`;
    return;
  }
  list.innerHTML = logs
    .map(
      (log) => `
        <div class="compact-item">
          <strong>${escapeHtml(log.question)}</strong>
          <span>${confidenceLabel(log.confidence)} · ${formatDate(log.created_at)}</span>
          <div class="compact-actions">
            <button class="ghost-btn small-btn" data-gap-log="${log.id}" data-gap-question="${escapeHtml(log.question)}">标记缺口</button>
          </div>
        </div>
      `,
    )
    .join("");
}

function renderDashboardDocuments(documents) {
  const list = $("#dashRecentDocs");
  if (!documents.length) {
    list.innerHTML = `<div class="empty">暂无最近文档。</div>`;
    return;
  }
  list.innerHTML = documents
    .map(
      (doc) => `
        <div class="compact-item">
          <strong>${escapeHtml(doc.title || doc.filename)}</strong>
          <span>${accessLabels[doc.access_level] || doc.access_level} · ${doc.chunk_count} 片段 · ${formatDate(doc.created_at)}</span>
        </div>
      `,
    )
    .join("");
}

function renderSystemStatus(dashboard) {
  const stats = dashboard.stats || {};
  const rows = [
    ["回答模式", stats.llm_enabled ? "大模型增强" : "本地抽取式"],
    ["文档健康", `${dashboard.ready_document_count || 0}/${stats.document_count || 0} 已入库`],
    ["知识缺口", `${dashboard.open_gap_count || 0} 个待处理`],
    ["员工权限", "仅问答工作台"],
    ["引用显示", "管理员可见"],
    ["敏感脱敏", "已启用"],
    ["安全拦截", "已启用"],
  ];
  $("#dashSystemStatus").innerHTML = rows
    .map(
      ([label, value]) => `
        <div class="status-row">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `,
    )
    .join("");
}

async function loadKnowledgeHealth() {
  if (!managementRoles.has(state.user?.role)) return;
  state.knowledgeHealth = await api("/api/knowledge-health");
  renderKnowledgeHealth();
}

function renderKnowledgeHealth() {
  const health = state.knowledgeHealth;
  if (!health) return;
  const metrics = health.metrics || {};
  const score = Number(health.score || 0);
  setText("#healthScore", score);
  setText("#healthGrade", health.grade || "-");
  setText("#healthSummary", health.summary || "");
  $("#healthScoreRing")?.style.setProperty("--score", `${score}%`);
  const gradeClass = score < 60 ? "danger" : score < 76 ? "warn" : "";
  if ($("#healthGrade")) $("#healthGrade").className = `badge ${gradeClass}`.trim();
  renderHealthMetrics(metrics);
  renderHealthRecommendations(health.recommendations || []);
  renderHealthDocuments(health.risk_documents || []);
  renderHealthLowConfidence(health.low_confidence_samples || []);
  renderHealthGapStatus(health.gap_status_counts || {});
}

function renderHealthMetrics(metrics) {
  const rows = [
    ["文档覆盖", `${metrics.ready_document_count || 0}/${metrics.document_count || 0}`],
    ["平均质量", percentText((metrics.avg_document_quality || 0) / 100)],
    ["未关闭缺口", metrics.open_gap_count || 0],
    ["低置信问题", metrics.low_confidence_count || 0],
    ["平均片段", metrics.avg_chunks_per_doc || 0],
    ["安全拦截率", percentText(metrics.blocked_ratio || 0)],
    ["平均置信度", percentText(metrics.avg_confidence || 0)],
    ["待优化文档", metrics.weak_document_count || 0],
  ];
  $("#healthMetricGrid").innerHTML = rows
    .map(
      ([label, value]) => `
        <article class="stat-card health-stat">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </article>
      `,
    )
    .join("");
}

function renderHealthRecommendations(items) {
  const list = $("#healthRecommendations");
  if (!items.length) {
    list.innerHTML = renderEmptyState("暂无优化建议", "当前知识库质量稳定，保持定期体检即可。");
    return;
  }
  list.innerHTML = items
    .map(
      (item) => `
        <div class="compact-item health-advice">
          <div class="panel-title">
            <strong>${escapeHtml(item.title)}</strong>
            <span class="badge ${item.priority === "高" ? "danger" : item.priority === "中" ? "warn" : "muted"}">${escapeHtml(item.priority)}</span>
          </div>
          <p>${escapeHtml(item.detail)}</p>
        </div>
      `,
    )
    .join("");
}

function renderHealthDocuments(items) {
  const list = $("#healthDocuments");
  const paging = state.pages.healthDocuments;
  paging.total = items.length;
  const totalPages = Math.max(Math.ceil(paging.total / paging.pageSize), 1);
  if (paging.page > totalPages) paging.page = totalPages;
  const start = (paging.page - 1) * paging.pageSize;
  const pageItems = items.slice(start, start + paging.pageSize);
  renderPagination("#healthDocumentPagination", "healthDocuments", {
    page: paging.page,
    page_size: paging.pageSize,
    total: paging.total,
    total_pages: totalPages,
  });
  if (!items.length) {
    list.innerHTML = renderEmptyState("暂无风险文档", "文档入库后系统会自动评估结构、长度、密级和更新时间。");
    return;
  }
  list.innerHTML = pageItems
    .map(
      (doc) => `
        <div class="compact-item health-doc">
          <div class="panel-title">
            <strong>${escapeHtml(doc.title)}</strong>
            <span class="${confidenceClass(doc.quality_score / 100)}">${doc.quality_score}</span>
          </div>
          <span>${accessLabels[doc.access_level] || doc.access_level} · ${doc.chunk_count} 个片段 · ${formatDate(doc.created_at)}</span>
          <p>${escapeHtml((doc.suggestions || []).join("；"))}</p>
          <button class="ghost-btn small-btn" data-health-document="${doc.id}">查看片段</button>
        </div>
      `,
    )
    .join("");
}

function renderHealthLowConfidence(items) {
  const list = $("#healthLowConfidence");
  if (!items.length) {
    list.innerHTML = renderEmptyState("暂无低置信样本", "系统还没有检测到需要复盘的低置信问答。");
    return;
  }
  list.innerHTML = items
    .map(
      (item) => `
        <div class="compact-item">
          <div class="panel-title">
            <strong>${escapeHtml(item.question)}</strong>
            <span class="${confidenceClass(item.confidence)}">${confidenceLabel(item.confidence)}</span>
          </div>
          <span>${formatDate(item.created_at)}</span>
          <button class="ghost-btn small-btn" data-gap-question="${escapeHtml(item.question)}" data-gap-log="${item.id}">转为知识缺口</button>
        </div>
      `,
    )
    .join("");
}

function renderHealthGapStatus(statusCounts) {
  const rows = [
    ["待补充", statusCounts.open || 0],
    ["处理中", statusCounts.processing || 0],
    ["已解决", statusCounts.resolved || 0],
  ];
  $("#healthGapStatus").innerHTML = rows
    .map(
      ([label, value]) => `
        <div class="status-row">
          <span>${escapeHtml(label)}</span>
          <strong>${value}</strong>
        </div>
      `,
    )
    .join("");
}

async function downloadHealthReport(format) {
  const response = await fetch(`/api/knowledge-health/export?format=${format}`, {
    headers: { Authorization: `Bearer ${state.token}` },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "导出失败");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `knowledge_health_report.${format === "csv" ? "csv" : "md"}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function loadQaFeedbacks() {
  if (!hasPermission("feedback.manage")) return;
  const paging = state.pages.feedback;
  const result = await api(`/api/qa-feedback?page=${paging.page}&page_size=${paging.pageSize}`);
  state.qaFeedbacks = result.items || [];
  Object.assign(paging, { page: result.page, pageSize: result.page_size, total: result.total });
  renderPagination("#feedbackPagination", "feedback", result);
  renderQaFeedbacks();
}

function renderQaFeedbacks() {
  const list = $("#feedbackList");
  if (!list) return;
  if (!state.qaFeedbacks.length) {
    list.innerHTML = renderEmptyState("暂无员工反馈", "员工在问答后点击有用、无用或需要补充资料，记录会出现在这里。");
    return;
  }
  list.innerHTML = state.qaFeedbacks
    .map(
      (item) => `
        <div class="compact-item feedback-item">
          <div class="panel-title">
            <strong>${escapeHtml(item.question)}</strong>
            <span class="badge ${feedbackBadgeClass(item.rating)}">${feedbackLabel(item.rating)}</span>
          </div>
          <span>${escapeHtml(item.display_name || item.username || "未知用户")} · 置信度 ${confidenceLabel(item.confidence)} · ${formatDate(item.created_at)}</span>
          ${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}
          <p>${escapeHtml(item.answer)}</p>
          <div class="compact-actions">
            ${item.gap_id ? `<span class="badge muted">已进入知识缺口 #${item.gap_id} · ${gapStatusLabels[item.gap_status] || item.gap_status}</span>` : ""}
            <button class="ghost-btn small-btn" data-feedback-log="${item.log_id}" data-feedback-question="${escapeHtml(item.question)}">转为知识缺口</button>
          </div>
        </div>
      `,
    )
    .join("");
}

function feedbackLabel(value) {
  return { helpful: "有用", unhelpful: "无用", needs_info: "需补充" }[value] || value;
}

function feedbackBadgeClass(value) {
  if (value === "helpful") return "";
  if (value === "needs_info") return "warn";
  return "danger";
}

function confidenceLabel(value) {
  if (value === null || value === undefined || value === "-") return "等待提问";
  return `${Math.round(Number(value) * 100)}%`;
}

function confidenceClass(value) {
  if (value >= 0.55) return "badge";
  if (value >= 0.18) return "badge warn";
  return "badge danger";
}

function renderEmptyState(title, detail, actionLabel = "", route = "") {
  return `
    <div class="empty empty-state">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(detail)}</span>
      ${actionLabel ? `<button class="ghost-btn small-btn" data-empty-route="${escapeHtml(route)}">${escapeHtml(actionLabel)}</button>` : ""}
    </div>
  `;
}

function renderPagination(selector, resource, result) {
  const container = $(selector);
  if (!container) return;
  const totalPages = Math.max(Number(result.total_pages || 0), 1);
  const page = Number(result.page || 1);
  container.innerHTML = `
    <span>共 ${Number(result.total || 0)} 条</span>
    <div class="pagination-controls">
      <span class="page-size-fixed">每页 5 条</span>
      <button class="ghost-btn small-btn" data-page-resource="${resource}" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>上一页</button>
      <strong>${page} / ${totalPages}</strong>
      <button class="ghost-btn small-btn" data-page-resource="${resource}" data-page="${page + 1}" ${page >= totalPages ? "disabled" : ""}>下一页</button>
    </div>
  `;
}

async function checkHealth() {
  try {
    await api("/api/health");
    $("#healthBadge").className = "badge";
    setText("#healthBadge", "在线");
  } catch {
    $("#healthBadge").className = "badge danger";
    setText("#healthBadge", "离线");
  }
}

async function loadDocuments() {
  const params = new URLSearchParams();
  const q = $("#docSearch")?.value?.trim();
  const access = $("#docAccessFilter")?.value;
  const type = $("#docTypeFilter")?.value;
  const sort = $("#docSort")?.value || "newest";
  const paging = state.pages.documents;
  if (q) params.set("q", q);
  if (access) params.set("access_level", access);
  if (type) params.set("file_type", type);
  params.set("sort", sort);
  params.set("page", paging.page);
  params.set("page_size", paging.pageSize);
  const result = await api(`/api/documents?${params.toString()}`);
  state.documents = result.items;
  paging.page = result.page;
  paging.pageSize = result.page_size;
  paging.total = result.total;
  setText("#docCount", result.total);
  renderPagination("#documentPagination", "documents", result);
  const list = $("#documentList");
  if (!state.documents.length) {
    list.innerHTML = renderEmptyState(
      "暂无可见文档",
      "可以调整筛选条件，或用管理账号上传企业制度文档。",
      hasPermission("documents.manage") ? "上传文档" : "",
      "documents",
    );
    return;
  }
  list.innerHTML = state.documents
    .map(
      (doc) => `
        <div class="document-item">
          <div>
            <strong>${escapeHtml(doc.title)}</strong>
            <span>${escapeHtml(doc.file_type.toUpperCase())} · V${doc.version || 1} · ${accessLabels[doc.access_level] || doc.access_level} · ${doc.chunk_count} 个片段 · 向量${doc.embedding_status === "ready" ? `已就绪 (${escapeHtml(doc.embedding_model || "默认模型")})` : doc.embedding_status === "failed" ? "失败" : "未配置"} · ${formatDate(doc.created_at)}</span>
            ${renderDocumentEditor(doc)}
          </div>
          <div class="document-actions">
            <button class="ghost-btn small-btn" data-view="${doc.id}">片段</button>
            <button class="ghost-btn small-btn" data-versions="${doc.id}">版本</button>
            <button class="ghost-btn small-btn ${hasPermission("documents.manage") ? "" : "hidden"}" data-reindex="${doc.id}">重索引</button>
            <button class="delete-btn ${hasPermission("documents.manage") ? "" : "hidden"}" title="删除文档" data-delete="${doc.id}">×</button>
          </div>
        </div>
      `,
    )
    .join("");
}

async function loadEvaluationCases() {
  const paging = state.pages.cases;
  const result = await api(`/api/evaluation/cases?page=${paging.page}&page_size=${paging.pageSize}`);
  state.evaluationCases = result.items || [];
  Object.assign(paging, { page: result.page, pageSize: result.page_size, total: result.total });
  renderPagination("#casePagination", "cases", result);
  renderEvaluationCases();
}

function renderEvaluationCases() {
  const list = $("#caseList");
  if (!list) return;
  if (!state.evaluationCases.length) {
    list.innerHTML = renderEmptyState("暂无评测用例", "补充标准问题、期望关键词和期望来源后，就能做批量质量评测。");
    return;
  }
  list.innerHTML = state.evaluationCases
    .map(
      (item) => {
        const readonly = item.is_golden;
        const sourceLabel = readonly ? `${item.dataset_version} · ${item.category}` : `自定义 · ${item.category}`;
        return `
        <div class="compact-item">
          <div class="panel-title case-title">
            <strong>用例 #${item.id}</strong>
            <span class="badge ${readonly ? "" : "muted"}">${readonly ? "黄金用例" : "自定义"}</span>
          </div>
          <span class="case-source">${escapeHtml(sourceLabel)}${item.case_key ? ` · ${escapeHtml(item.case_key)}` : ""}</span>
          <div class="case-form">
            <input class="input" data-case-question="${item.id}" value="${escapeHtml(item.question)}" ${readonly ? "disabled" : ""} />
            <input class="input" data-case-keywords="${item.id}" value="${escapeHtml(item.expected_keywords.join(", "))}" ${readonly ? "disabled" : ""} />
            <input class="input" data-case-documents="${item.id}" value="${escapeHtml(item.expected_documents.join(", "))}" ${readonly ? "disabled" : ""} />
            <label class="inline-check"><input type="checkbox" data-case-should-answer="${item.id}" ${item.should_answer ? "checked" : ""} ${readonly ? "disabled" : ""} /> 应有答案</label>
            ${readonly ? "" : `<div class="compact-actions"><button class="ghost-btn small-btn" data-case-save="${item.id}">保存</button><button class="delete-btn" title="删除用例" data-case-delete="${item.id}">×</button></div>`}
          </div>
        </div>
      `;
      },
    )
    .join("");
}

async function createEvaluationCase() {
  setText("#caseStatus", "正在新增...");
  try {
    await api("/api/evaluation/cases", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({
        question: $("#caseQuestion").value.trim(),
        expected_keywords: splitValue($("#caseKeywords").value),
        expected_documents: splitValue($("#caseDocuments").value),
        should_answer: $("#caseShouldAnswer").checked,
      }),
    });
    $("#caseQuestion").value = "";
    $("#caseKeywords").value = "";
    $("#caseDocuments").value = "";
    $("#caseShouldAnswer").checked = true;
    setText("#caseStatus", "新增成功。");
    await loadEvaluationCases();
  } catch (error) {
    setText("#caseStatus", error.message);
  }
}

async function saveEvaluationCase(id) {
  await api(`/api/evaluation/cases/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({
      question: document.querySelector(`[data-case-question="${id}"]`)?.value.trim(),
      expected_keywords: splitValue(document.querySelector(`[data-case-keywords="${id}"]`)?.value || ""),
      expected_documents: splitValue(document.querySelector(`[data-case-documents="${id}"]`)?.value || ""),
      should_answer: document.querySelector(`[data-case-should-answer="${id}"]`)?.checked ?? true,
    }),
  });
  await loadEvaluationCases();
}

async function deleteEvaluationCase(id) {
  await api(`/api/evaluation/cases/${id}`, { method: "DELETE" });
  await loadEvaluationCases();
}

async function loadKnowledgeGaps() {
  if (!hasPermission("gaps.manage")) return;
  const status = $("#gapStatusFilter")?.value || "";
  const paging = state.pages.gaps;
  const params = new URLSearchParams({
    page: String(paging.page),
    page_size: String(paging.pageSize),
  });
  if (status) params.set("status", status);
  const result = await api(`/api/knowledge-gaps?${params.toString()}`);
  state.knowledgeGaps = result.items || [];
  Object.assign(paging, { page: result.page, pageSize: result.page_size, total: result.total });
  renderPagination("#gapPagination", "gaps", result);
  renderKnowledgeGaps();
}

function renderKnowledgeGaps() {
  const list = $("#gapList");
  if (!list) return;
  if (!state.knowledgeGaps.length) {
    list.innerHTML = renderEmptyState("暂无知识缺口", "低置信度问题可一键沉淀到这里，后续补充制度文档并关闭任务。");
    return;
  }
  list.innerHTML = state.knowledgeGaps
    .map(
      (gap) => `
        <div class="compact-item gap-item">
          <div class="panel-title">
            <strong>${escapeHtml(gap.question)}</strong>
            <span class="badge ${gap.status === "resolved" ? "" : gap.status === "processing" ? "warn" : "danger"}">${gapStatusLabels[gap.status] || gap.status}</span>
          </div>
          <span>
            ${gap.source_log_id ? `来源问答 #${gap.source_log_id} · ` : ""}
            优化前 ${gap.before_score == null ? "-" : percentText(gap.before_score)}
            · 优化后 ${gap.after_score == null ? "-" : percentText(gap.after_score)}
            · ${formatDate(gap.created_at)}
          </span>
          <textarea class="input gap-note" data-gap-note="${gap.id}" placeholder="处理备注，例如：需要补充报销制度第 3 条">${escapeHtml(gap.note || "")}</textarea>
          <input class="input" data-gap-action="${gap.id}" value="${escapeHtml(gap.resolution_action || "")}" placeholder="处理动作，例如：补充制度文档并重建索引" />
          <div class="gap-actions">
            <select class="input" data-gap-status="${gap.id}">
              <option value="open" ${gap.status === "open" ? "selected" : ""}>待补充</option>
              <option value="processing" ${gap.status === "processing" ? "selected" : ""}>处理中</option>
              <option value="resolved" ${gap.status === "resolved" ? "selected" : ""}>已解决</option>
              <option value="closed" ${gap.status === "closed" ? "selected" : ""}>无需处理</option>
            </select>
            <button class="ghost-btn small-btn" data-gap-save="${gap.id}">保存</button>
            <button class="ghost-btn small-btn" data-gap-recheck="${gap.id}">重新评测</button>
            <button class="ghost-btn small-btn" data-gap-resolve="${gap.id}">标记解决</button>
            <button class="delete-btn" title="删除知识缺口" data-gap-delete="${gap.id}">×</button>
          </div>
        </div>
      `,
    )
    .join("");
}

async function createKnowledgeGap(question, sourceLogId = null) {
  const payload = { question: question.trim() };
  if (!payload.question) {
    alert("请先输入一个问题。");
    return;
  }
  if (sourceLogId) payload.source_log_id = Number(sourceLogId);
  const result = await api("/api/knowledge-gaps", {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify(payload),
  });
  alert(result.duplicate ? "该知识缺口已存在。" : "已标记为知识缺口。");
  await loadDashboard();
  if (state.route === "gaps") await loadKnowledgeGaps();
}

async function createGapFromCurrentQuestion() {
  await createKnowledgeGap($("#questionInput")?.value || "");
}

async function saveKnowledgeGap(id, forcedStatus = "") {
  const payload = {
    status: forcedStatus || document.querySelector(`[data-gap-status="${id}"]`)?.value,
    note: document.querySelector(`[data-gap-note="${id}"]`)?.value || "",
    resolution_action: document.querySelector(`[data-gap-action="${id}"]`)?.value || "",
  };
  await api(`/api/knowledge-gaps/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify(payload),
  });
  await loadKnowledgeGaps();
  await loadDashboard();
}

async function deleteKnowledgeGap(id) {
  if (!confirm("确认删除这个知识缺口？")) return;
  await api(`/api/knowledge-gaps/${id}`, { method: "DELETE" });
  await loadKnowledgeGaps();
  await loadDashboard();
}

async function loadAuditLogs() {
  if (!hasPermission("audit.view")) return;
  const paging = state.pages.audit;
  const result = await api(`/api/audit-logs?page=${paging.page}&page_size=${paging.pageSize}`);
  state.auditLogs = result.items || [];
  Object.assign(paging, { page: result.page, pageSize: result.page_size, total: result.total });
  renderPagination("#auditPagination", "audit", result);
  const list = $("#auditList");
  if (!state.auditLogs.length) {
    list.innerHTML = renderEmptyState("暂无操作审计记录", "上传、删除、重索引、用户变更等管理动作会记录在这里。");
    return;
  }
  list.innerHTML = state.auditLogs
    .map(
      (item) => `
        <div class="log-item">
          <div class="panel-title">
            <strong>${escapeHtml(item.action)}</strong>
            <span>${escapeHtml(item.target_type)} #${item.target_id ?? "-"}</span>
          </div>
          <span>${escapeHtml(item.display_name || item.username || "未知用户")} · ${formatDate(item.created_at)}</span>
          <p>${escapeHtml(JSON.stringify(item.detail, null, 2))}</p>
        </div>
      `,
    )
    .join("");
}

async function clearAuditLogs() {
  if (state.user?.role !== "admin") return;
  const confirmed = window.confirm("确定要清理操作审计记录吗？系统会保留一条本次清理动作。");
  if (!confirmed) return;
  const button = $("#clearAuditBtn");
  if (button) button.disabled = true;
  setText("#auditStatus", "正在清理审计记录...");
  try {
    const result = await api("/api/audit-logs", { method: "DELETE" });
    const count = result.deleted_count || 0;
    setText(
      "#auditStatus",
      count ? `已清理 ${count} 条旧记录，并保留本次清理记录。` : "没有旧记录可清理，已记录本次操作。",
    );
    await loadAuditLogs();
  } catch (error) {
    setText("#auditStatus", error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderDocumentEditor(doc) {
  if (!hasPermission("documents.manage")) return "";
  return `
    <div class="document-edit">
      <input class="input" data-title="${doc.id}" value="${escapeHtml(doc.title)}" />
      <select class="input" data-access="${doc.id}">
        ${Object.entries(accessLabels)
          .map(([value, label]) => `<option value="${value}" ${doc.access_level === value ? "selected" : ""}>${label}</option>`)
          .join("")}
      </select>
      <button class="ghost-btn small-btn" data-save="${doc.id}">保存</button>
    </div>
  `;
}

async function loadDocumentChunks(documentId) {
  if (state.selectedDocumentId !== Number(documentId)) state.pages.chunks.page = 1;
  state.selectedDocumentId = Number(documentId);
  const paging = state.pages.chunks;
  const detail = await api(`/api/documents/${documentId}/chunks?page=${paging.page}&page_size=${paging.pageSize}`);
  const chunks = detail.items || [];
  Object.assign(paging, { page: detail.page, pageSize: detail.page_size, total: detail.total });
  setText("#chunkCountBadge", `V${detail.document.version || 1} · ${accessLabels[detail.document.access_level] || detail.document.access_level} · ${detail.total} 个片段`);
  renderPagination("#chunkPagination", "chunks", detail);
  const list = $("#documentDetail");
  if (!chunks.length) {
    list.innerHTML = renderEmptyState("该文档暂无知识片段", "可以点击文档列表中的“重索引”重新切分，或检查原始文件内容。");
    return;
  }
  list.innerHTML = chunks
    .map(
      (chunk) => `
        <article class="chunk-item">
          <div class="panel-title">
            <strong>${escapeHtml(detail.document.title)} · 片段 #${chunk.chunk_index + 1}</strong>
            <span>${formatDate(chunk.created_at)}</span>
          </div>
          <p>${escapeHtml(chunk.content)}</p>
        </article>
      `,
    )
    .join("");
}

async function loadDocumentVersions(documentId) {
  if (state.selectedDocumentId !== Number(documentId)) state.pages.versions.page = 1;
  state.selectedDocumentId = Number(documentId);
  const paging = state.pages.versions;
  const result = await api(`/api/documents/${documentId}/versions?page=${paging.page}&page_size=${paging.pageSize}`);
  state.documentVersions = result.items || [];
  Object.assign(paging, { page: result.page, pageSize: result.page_size, total: result.total });
  renderPagination("#versionPagination", "versions", result);
  renderDocumentVersions();
}

function renderDocumentVersions() {
  const list = $("#documentVersions");
  if (!list) return;
  if (!state.documentVersions.length) {
    list.innerHTML = renderEmptyState("暂无版本记录", "上传、修改标题/密级或重索引后会在这里形成版本历史。");
    return;
  }
  const actionLabels = {
    initial: "历史导入",
    upload: "首次上传",
    metadata_update: "信息变更",
    reindex: "重新索引",
  };
  list.innerHTML = state.documentVersions
    .map(
      (item) => `
        <div class="compact-item version-item">
          <div class="panel-title">
            <strong>V${item.version} · ${escapeHtml(actionLabels[item.action] || item.action)}</strong>
            <span class="badge muted">${escapeHtml(accessLabels[item.access_level] || item.access_level)}</span>
          </div>
          <span>${escapeHtml(item.title)} · ${item.chunk_count} 个片段 · ${formatDate(item.created_at)}</span>
          <p>操作人：${escapeHtml(item.display_name || item.username || "系统")}</p>
        </div>
      `,
    )
    .join("");
}

async function loadStats() {
  state.stats = await api("/api/stats");
  setText("#statChunks", state.stats.chunk_count);
  setText("#statBlocked", state.stats.blocked_count);
  setText("#statConfidence", percentText(state.stats.avg_confidence));
  setText("#statEvalScore", percentText(state.stats.avg_evaluation_score));
  $("#confidenceMeter").style.width = percentText(state.stats.avg_confidence);
  $("#evalMeter").style.width = percentText(state.stats.avg_evaluation_score);
}

async function loadAnalytics() {
  state.analytics = await api("/api/analytics");
  renderAnalytics();
}

function renderAnalytics() {
  if (!state.analytics) return;
  renderBarChart(
    "#accessChart",
    state.analytics.access_distribution.map((item) => ({
      label: accessLabels[item.access_level] || item.access_level,
      value: item.count,
    })),
  );
  renderBarChart(
    "#trendChart",
    state.analytics.qa_trend.map((item) => ({ label: item.day.slice(5), value: item.count })),
  );
  renderBarChart("#scoreChart", [
    { label: "低分", value: state.analytics.evaluation_buckets.low },
    { label: "中等", value: state.analytics.evaluation_buckets.medium },
    { label: "高分", value: state.analytics.evaluation_buckets.high },
  ]);
}

function renderBarChart(selector, rows) {
  const list = $(selector);
  if (!rows.length) {
    list.innerHTML = renderEmptyState("暂无数据", "系统产生问答、评测或文档记录后会自动形成图表。");
    return;
  }
  const max = Math.max(...rows.map((row) => Number(row.value) || 0), 1);
  list.innerHTML = rows
    .map((row) => {
      const value = Number(row.value) || 0;
      return `
        <div class="bar-row">
          <span>${escapeHtml(row.label)}</span>
          <div class="bar-track"><i class="bar-fill" style="width:${Math.max(4, (value / max) * 100)}%"></i></div>
          <strong>${value}</strong>
        </div>
      `;
    })
    .join("");
}

async function runRetrieval() {
  const query = $("#retrievalQuery").value.trim();
  const topK = Number($("#retrievalTopK").value || 5);
  if (!query) {
    setText("#retrievalStatus", "请输入检索问题。");
    return;
  }
  setText("#retrievalStatus", "正在检索...");
  $("#retrievalBtn").disabled = true;
  try {
    const params = new URLSearchParams({ q: query, top_k: String(topK) });
    const result = await api(`/api/search?${params.toString()}`);
    setText("#retrievalCount", `${result.hits.length} 个命中`);
    setText("#retrievalStatus", "");
    renderRetrievalHits(result.hits, result.explanation);
  } catch (error) {
    setText("#retrievalStatus", error.message);
  } finally {
    $("#retrievalBtn").disabled = false;
  }
}

function renderRetrievalHits(hits, explanation = null) {
  const list = $("#retrievalList");
  if (!hits.length) {
    list.innerHTML = renderEmptyState("没有命中片段", "换一个更接近文档原文的问法，或先补充相关资料后再检索。", "去文档管理", "documents");
    return;
  }
  const accessText = (explanation?.permission_scope || []).map((level) => accessLabels[level] || level).join("、");
  const queryTerms = (explanation?.query_terms || []).slice(0, 12);
  list.innerHTML = `
    <article class="retrieval-explain-card">
      <div class="panel-title">
        <span>检索解释</span>
        <span class="badge muted">${escapeHtml(explanation?.algorithm || "BM25")}</span>
      </div>
      <p>${escapeHtml(explanation?.ranking_rule || "按相似度排序，并结合当前角色权限过滤可见文档。")}</p>
      <div class="term-row">
        <span>权限范围：${escapeHtml(accessText || "未识别")}</span>
        ${queryTerms.map((term) => `<i>${escapeHtml(term)}</i>`).join("")}
      </div>
    </article>
  `;
  list.innerHTML += hits
    .map(
      (hit) => `
        <article class="citation-item retrieval-hit">
          <div class="panel-title">
            <strong>${escapeHtml(hit.document_title)}</strong>
            <span class="badge muted">${Math.round(hit.score * 100)}%</span>
          </div>
          <span>片段 #${hit.chunk_index + 1} · ${accessLabels[hit.document_access_level] || hit.document_access_level}</span>
          <span>BM25 ${Number(hit.score_breakdown?.bm25 || 0).toFixed(3)} · Vector ${Number(hit.score_breakdown?.vector || 0).toFixed(3)} · Rerank ${Number(hit.score_breakdown?.rerank || 0).toFixed(3)}</span>
          <div class="term-row">
            <span>${escapeHtml(hit.why || "按相似度命中")}</span>
            ${(hit.matched_terms || []).slice(0, 10).map((term) => `<i>${escapeHtml(term)}</i>`).join("")}
          </div>
          <p>${escapeHtml(hit.content)}</p>
        </article>
      `,
    )
    .join("");
}

async function loadLogs() {
  const paging = state.pages.logs;
  const result = await api(`/api/logs?page=${paging.page}&page_size=${paging.pageSize}`);
  state.logs = result.items || [];
  Object.assign(paging, { page: result.page, pageSize: result.page_size, total: result.total });
  renderPagination("#logPagination", "logs", result);
  setText("#logCount", result.total);
  const list = $("#logList");
  if (!state.logs.length) {
    list.innerHTML = renderEmptyState("暂无问答日志", "在问答工作台提问后，这里会记录问题、回答、置信度和引用来源。", "去提问", "qa");
    return;
  }
  list.innerHTML = state.logs
    .map((log) => {
      const badge = log.blocked ? `<span class="badge danger">已拦截</span>` : `<span class="badge muted">${confidenceLabel(log.confidence)}</span>`;
      const actor = log.display_name ? ` · ${escapeHtml(log.display_name)}` : "";
      return `
        <div class="log-item">
          <div class="panel-title">
            <strong>${escapeHtml(log.question)}</strong>
            ${badge}
          </div>
          <span>${formatDate(log.created_at)}${actor}${log.block_reason ? ` · ${escapeHtml(log.block_reason)}` : ""}</span>
          <p class="log-answer-preview" title="${escapeHtml(log.answer)}">${escapeHtml(log.answer)}</p>
        </div>
      `;
    })
    .join("");
}

async function clearLogs() {
  if (state.user?.role !== "admin") return;
  const confirmed = window.confirm("确定要清理问答审计日志吗？相关问答反馈会同步清理，知识缺口会保留但取消来源日志关联。");
  if (!confirmed) return;
  const button = $("#clearLogsBtn");
  if (button) button.disabled = true;
  setText("#logsStatus", "正在清理问答审计日志...");
  try {
    const result = await api("/api/logs", { method: "DELETE" });
    setText(
      "#logsStatus",
      `已清理 ${result.deleted_logs || 0} 条问答日志、${result.deleted_feedback || 0} 条反馈记录。`,
    );
    await loadLogs();
    await loadStats();
    await loadDashboard();
    await loadKnowledgeHealth();
  } catch (error) {
    setText("#logsStatus", error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function loadEvaluations() {
  const paging = state.pages.evaluations;
  const result = await api(`/api/evaluations?page=${paging.page}&page_size=${paging.pageSize}`);
  state.evaluations = result.items || [];
  Object.assign(paging, { page: result.page, pageSize: result.page_size, total: result.total });
  renderPagination("#evaluationPagination", "evaluations", result);
  const list = $("#evaluationList");
  if (!state.evaluations.length) {
    list.innerHTML = renderEmptyState("暂无评测记录", "运行单条评测或批量评测后，可以在这里查看得分和来源命中率。");
    return;
  }
  list.innerHTML = state.evaluations
    .map(
      (item) => `
        <div class="log-item">
          <div class="panel-title">
            <strong>${escapeHtml(item.question)}</strong>
            <span class="badge muted">${Math.round(item.score * 100)}%</span>
          </div>
          <span>关键词：${escapeHtml(item.expected_keywords.join(", ") || "未设置")} · 来源命中：${percentText(item.citation_hit || 0)} · ${formatDate(item.created_at)}</span>
          <p>${escapeHtml(item.answer)}</p>
        </div>
      `,
    )
    .join("");
}

async function loadBatchRuns() {
  const paging = state.pages.batches;
  const result = await api(`/api/evaluation/batch/runs?page=${paging.page}&page_size=${paging.pageSize}`);
  state.batchRuns = result.items || [];
  Object.assign(paging, { page: result.page, pageSize: result.page_size, total: result.total });
  renderPagination("#batchPagination", "batches", result);
  renderBatchRuns();
  renderLatestQualityGate(state.batchRuns[0]);
}

function renderLatestQualityGate(latest) {
  if (!latest) {
    $("#batchSummary").innerHTML = `<span>暂无质量门禁结果。</span>`;
    return;
  }
  const gatePassed = latest.gate_status === "passed";
  const failed = (latest.failed_metrics || []).map((metric) => evaluationMetricLabels[metric] || metric);
  const baseline = latest.baseline_reference || (latest.baseline_run_id ? `历史运行 #${latest.baseline_run_id}` : "无兼容基线");
  $("#batchSummary").innerHTML = `
    <span class="badge ${gatePassed ? "" : "danger"}">${gatePassed ? "门禁通过" : "门禁失败"}</span>
    <strong>${percentText(latest.answer_accuracy)}</strong>
    <span>${escapeHtml(latest.dataset_version)} · ${escapeHtml(latest.dataset_hash.slice(0, 12))} · Top ${latest.top_k} · ${baseline}</span>
    <span>平均置信度：${percentText(latest.avg_confidence)}</span>
    <span>Recall@K：${percentText(latest.recall_at_k)}</span>
    <span>MRR：${Number(latest.mrr || 0).toFixed(3)}</span>
    <span>答案正确率：${percentText(latest.answer_accuracy)}</span>
    <span>拒答准确率：${percentText(latest.abstention_accuracy)}</span>
    ${failed.length ? `<span class="gate-failure">未通过：${escapeHtml(failed.join("、"))}</span>` : ""}
  `;
}

function renderBatchRuns() {
  const list = $("#batchRunList");
  if (!state.batchRuns.length) {
    list.innerHTML = "";
    return;
  }
  list.innerHTML = state.batchRuns
    .slice(0, 5)
    .map(
      (run) => {
        const gatePassed = run.gate_status === "passed";
        const deltas = Object.entries(run.metric_deltas || {})
          .map(([metric, value]) => `${evaluationMetricLabels[metric] || metric} ${Number(value) >= 0 ? "+" : ""}${percentText(value)}`)
          .join(" · ");
        return `
        <div class="compact-item">
          <div class="panel-title case-title">
            <strong>质量门禁 #${run.id}</strong>
            <span class="badge ${gatePassed ? "" : "danger"}">${gatePassed ? "通过" : "失败"}</span>
          </div>
          <span>${escapeHtml(run.dataset_version)} · ${escapeHtml(run.dataset_hash.slice(0, 12))} · Top ${run.top_k} · ${escapeHtml(run.baseline_reference || (run.baseline_run_id ? `历史运行 #${run.baseline_run_id}` : "无兼容基线"))}</span>
          <span>${run.total} 条 · Recall@K ${percentText(run.recall_at_k)} · MRR ${Number(run.mrr || 0).toFixed(3)} · 答案正确率 ${percentText(run.answer_accuracy)} · 拒答准确率 ${percentText(run.abstention_accuracy)} · ${formatDate(run.created_at)}</span>
          ${deltas ? `<span>相对基线：${escapeHtml(deltas)}</span>` : ""}
          <div class="compact-actions">
            <button class="ghost-btn small-btn" data-export-md="${run.id}">导出 Markdown</button>
            <button class="ghost-btn small-btn" data-export-csv="${run.id}">导出 CSV</button>
          </div>
        </div>
      `;
      },
    )
    .join("");
}

async function loadRolePermissions() {
  if (!hasPermission("roles.manage")) return;
  const [catalog, matrix] = await Promise.all([
    api("/api/permissions/catalog"),
    api("/api/role-permissions"),
  ]);
  state.permissionCatalog = catalog.items || [];
  state.rolePermissions = matrix.roles || {};
  renderRolePermissions();
}

async function loadQualityAssessments() {
  if (!hasPermission("evaluation.manage")) return;
  const paging = state.pages.quality;
  const params = new URLSearchParams({
    page: String(paging.page),
    page_size: String(paging.pageSize),
  });
  const q = $("#qualitySearch")?.value?.trim();
  const level = $("#qualityLevelFilter")?.value;
  if (q) params.set("q", q);
  if (level) params.set("level", level);
  const result = await api(`/api/quality-assessments?${params.toString()}`);
  state.qualityAssessments = result.items || [];
  paging.page = result.page;
  paging.pageSize = result.page_size;
  paging.total = result.total;
  renderQualityAssessments();
  renderPagination("#qualityPagination", "quality", result);
}

function qualityLevelLabel(level) {
  return {
    passed: "通过",
    watch: "关注",
    review: "待复核",
    blocked: "已拦截",
    failed: "筛查失败",
  }[level] || level;
}

function renderQualityAssessments() {
  const container = $("#qualityAssessmentList");
  if (!container) return;
  if (!state.qualityAssessments.length) {
    container.innerHTML = renderEmptyState(
      "暂无质量筛查记录",
      "普通员工完成提问后，系统会自动计算置信度、引用质量和综合质量分。",
    );
    return;
  }
  container.innerHTML = `
    <table class="business-table">
      <thead>
        <tr>
          <th>问题</th>
          <th>提问人</th>
          <th>置信度</th>
          <th>最高相似度</th>
          <th>质量分</th>
          <th>等级</th>
          <th>风险原因</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${state.qualityAssessments
          .map(
            (item) => `
              <tr>
                <td class="table-primary">${escapeHtml(item.question)}</td>
                <td>${escapeHtml(item.display_name || item.username || "未知用户")}</td>
                <td>${percentText(item.confidence_score)}</td>
                <td>${percentText(item.top_similarity_score)}</td>
                <td>${percentText(item.quality_score)}</td>
                <td><span class="badge ${["review", "failed"].includes(item.quality_level) ? "danger" : item.quality_level === "watch" ? "warn" : ""}">${qualityLevelLabel(item.quality_level)}</span></td>
                <td>${escapeHtml((item.risk_reasons || []).join("、") || "无")}</td>
                <td>
                  ${item.status === "failed" ? `<button class="ghost-btn small-btn" data-quality-retry="${item.log_id}">重试</button>` : ""}
                </td>
              </tr>
            `,
          )
          .join("")}
      </tbody>
    </table>
  `;
}

async function retryQualityAssessment(logId) {
  await api(`/api/quality-assessments/${logId}/retry`, { method: "POST" });
  await loadQualityAssessments();
}

function rolePermissionLocked(role, code) {
  if (code === "qa.use") return true;
  if (role === "admin" && ["users.manage", "roles.manage", "audit.view"].includes(code)) return true;
  if (role !== "admin" && ["users.manage", "roles.manage"].includes(code)) return true;
  return false;
}

function renderRolePermissions() {
  const container = $("#rolePermissionMatrix");
  if (!container) return;
  const roles = ["admin", "tech", "employee"];
  container.innerHTML = `
    <div class="permission-row permission-head">
      <strong>功能权限</strong>
      ${roles.map((role) => `<strong>${roleLabels[role]}</strong>`).join("")}
    </div>
    ${state.permissionCatalog
      .map(
        (permission) => `
          <div class="permission-row">
            <div>
              <strong>${escapeHtml(permission.name)}</strong>
              <span>${escapeHtml(permission.description)}</span>
            </div>
            ${roles
              .map((role) => {
                const checked = (state.rolePermissions[role] || []).includes(permission.code);
                const visualOnly = role === "employee";
                const locked = visualOnly || rolePermissionLocked(role, permission.code);
                const displayedChecked = visualOnly ? permission.code === "qa.use" : checked;
                return `
                  <label class="permission-cell ${locked ? "locked" : ""}">
                    <input
                      type="checkbox"
                      data-role-permission="${role}"
                      data-permission-code="${permission.code}"
                      data-visual-only="${visualOnly ? "true" : ""}"
                      ${displayedChecked ? "checked" : ""}
                      ${locked ? "disabled" : ""}
                    />
                    <span>${visualOnly ? "锁定" : locked ? "锁定" : checked ? "允许" : "禁止"}</span>
                  </label>
                `;
              })
              .join("")}
          </div>
        `,
      )
      .join("")}
  `;
}

async function saveRolePermissions() {
  setText("#rolePermissionStatus", "正在保存...");
  try {
    for (const role of ["admin", "tech", "employee"]) {
      const selected = $$(`[data-role-permission="${role}"]`)
        .filter((input) => input.checked && input.dataset.visualOnly !== "true")
        .map((input) => input.dataset.permissionCode);
      const result = await api(`/api/role-permissions/${role}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({ permissions: selected }),
      });
      state.rolePermissions[role] = result.permissions;
    }
    setText("#rolePermissionStatus", "权限配置已保存。");
    const current = await api("/api/auth/me");
    state.user = current.user;
    state.permissions = new Set(current.permissions || []);
    applyUserState();
    renderRolePermissions();
  } catch (error) {
    setText("#rolePermissionStatus", error.message);
  }
}

async function changePage(resource, page) {
  const target = state.pages[resource];
  if (!target || page < 1) return;
  target.page = page;
  if (resource === "documents") await loadDocuments();
  if (resource === "users") await loadUsers();
  if (resource === "quality") await loadQualityAssessments();
  if (resource === "logs") await loadLogs();
  if (resource === "agentRuns") await loadAgentRuns();
  if (resource === "evaluations") await loadEvaluations();
  if (resource === "cases") await loadEvaluationCases();
  if (resource === "batches") await loadBatchRuns();
  if (resource === "feedback") await loadQaFeedbacks();
  if (resource === "gaps") await loadKnowledgeGaps();
  if (resource === "healthDocuments") renderKnowledgeHealth();
  if (resource === "audit") await loadAuditLogs();
  if (resource === "chunks" && state.selectedDocumentId) await loadDocumentChunks(state.selectedDocumentId);
  if (resource === "versions" && state.selectedDocumentId) await loadDocumentVersions(state.selectedDocumentId);
}

async function runAgentFromWorkspace() {
  const goal = $("#agentGoalInput").value.trim();
  if (!goal) {
    setText("#agentRunStatus", "请输入任务目标。");
    return;
  }
  await submitAgentTask(goal);
}

async function submitAgentTask(goal) {
  $("#runAgentBtn").disabled = true;
  $("#cancelAgentBtn").disabled = true;
  $("#agentStatusBadge").className = "badge muted";
  $("#agentStatusBadge").textContent = "提交中";
  setText("#agentRunStatus", "正在创建持久化任务...");
  setText("#agentRunIdBadge", "未生成");
  $("#agentFinalAnswer").textContent = "Agent 任务正在进入执行队列...";
  renderAgentToolTimeline([]);
  try {
    const result = await api("/api/agent/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ goal, top_k: 5, idempotency_key: makeAgentIdempotencyKey("run") }),
    });
    state.activeAgentRunId = result.run_id;
    renderAgentResult(result);
    setText("#agentRunStatus", `任务已提交：#${result.run_id}`);
    await monitorAgentRun(result.run_id);
  } catch (error) {
    $("#agentStatusBadge").className = "badge danger";
    $("#agentStatusBadge").textContent = "失败";
    $("#agentFinalAnswer").textContent = error.message;
    setText("#agentRunStatus", error.message);
    state.activeAgentRunId = null;
  } finally {
    updateAgentTaskControls();
  }
}

async function monitorAgentRun(runId) {
  const generation = ++state.agentPollGeneration;
  while (generation === state.agentPollGeneration) {
    const result = await api(`/api/agent/runs/${runId}`);
    renderAgentResult(result);
    if (isAgentTerminal(result.status)) {
      state.activeAgentRunId = null;
      setText("#agentRunStatus", `任务${toolStatusLabel(result.status)}：#${runId}`);
      updateAgentTaskControls();
      await loadAgentRuns();
      return result;
    }
    setText("#agentRunStatus", `任务${toolStatusLabel(result.status)}：#${runId}`);
    updateAgentTaskControls();
    await wait(800);
  }
  return null;
}

async function cancelActiveAgentRun() {
  const runId = state.activeAgentRunId;
  if (!runId) return;
  $("#cancelAgentBtn").disabled = true;
  try {
    const result = await api(`/api/agent/runs/${runId}/cancel`, { method: "POST" });
    renderAgentResult(result);
    setText("#agentRunStatus", `已请求取消：#${runId}`);
  } catch (error) {
    setText("#agentRunStatus", error.message);
  } finally {
    updateAgentTaskControls();
  }
}

async function retryAgentRun(runId) {
  if (state.activeAgentRunId) return;
  $("#runAgentBtn").disabled = true;
  try {
    const result = await api(`/api/agent/runs/${runId}/retry`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ idempotency_key: makeAgentIdempotencyKey(`retry-${runId}`) }),
    });
    state.activeAgentRunId = result.run_id;
    renderAgentResult(result);
    setText("#agentRunStatus", `已重试为新任务：#${result.run_id}`);
    await monitorAgentRun(result.run_id);
  } catch (error) {
    setText("#agentRunStatus", error.message);
    state.activeAgentRunId = null;
  } finally {
    updateAgentTaskControls();
  }
}

function updateAgentTaskControls() {
  const active = Boolean(state.activeAgentRunId);
  $("#runAgentBtn").disabled = active;
  $("#cancelAgentBtn").disabled = !active;
}

function isAgentTerminal(status) {
  return ["completed", "blocked", "failed", "cancelled"].includes(status);
}

function makeAgentIdempotencyKey(prefix) {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function loadAgentRuns() {
  if (!hasPermission("qa.use")) return;
  const paging = state.pages.agentRuns;
  const result = await api(`/api/agent/runs?page=${paging.page}&page_size=${paging.pageSize}`);
  state.agentRuns = result.items || [];
  paging.page = result.page;
  paging.pageSize = result.page_size;
  paging.total = result.total;
  renderPagination("#agentRunPagination", "agentRuns", result);
  renderAgentRuns();
}

function renderAgentResult(result) {
  const danger = ["blocked", "failed", "cancelled"].includes(result.status);
  const muted = ["queued", "cancel_requested"].includes(result.status);
  $("#agentStatusBadge").className = danger ? "badge danger" : muted ? "badge muted" : "badge";
  $("#agentStatusBadge").textContent = toolStatusLabel(result.status);
  setText("#agentRunIdBadge", result.run_id ? `#${result.run_id}` : "历史记录");
  const pendingText = result.status === "queued" ? "任务正在等待可用执行槽位。" : "Agent 正在规划并调用工具...";
  $("#agentFinalAnswer").textContent = result.final_answer || pendingText;
  const plan = result.plan || {};
  const plannerLabel = plan.mode === "llm" ? "模型规划" : plan.mode === "pending" || !plan.mode ? "等待规划" : "确定性规划";
  const fallback = plan.fallback_reason ? ` · 降级原因 ${plan.fallback_reason}` : "";
  setText("#agentPlanSummary", `计划：${plannerLabel} · ${(plan.steps || []).join(" → ") || "未记录"}${fallback}`);
  renderAgentToolTimeline(result.tool_calls || []);
}

function renderAgentToolTimeline(toolCalls) {
  const list = $("#agentToolTimeline");
  setText("#agentToolCount", toolCalls.length);
  if (!toolCalls.length) {
    list.innerHTML = renderEmptyState("暂无工具调用", "运行 Agent 后会显示每一步工具调用。");
    return;
  }
  list.innerHTML = toolCalls
    .map(
      (call, index) => `
        <div class="tool-call-item">
          <div class="tool-call-head">
            <strong>${index + 1}. ${escapeHtml(call.tool_name)}</strong>
            <div class="compact-actions">
              <span class="status-mini">${Number(call.attempts || 1)} 次 · ${Number(call.duration_ms || 0).toFixed(0)} ms</span>
              <span class="badge ${call.status === "skipped" || call.status === "blocked" ? "muted" : ""}">${escapeHtml(toolStatusLabel(call.status))}</span>
            </div>
          </div>
          <div class="tool-output">
            <span>输入</span>
            <pre>${escapeHtml(formatToolPayload(call.input))}</pre>
            <span>输出</span>
            <pre>${escapeHtml(formatToolPayload(call.output))}</pre>
          </div>
        </div>
      `,
    )
    .join("");
}

function renderAgentRuns() {
  const list = $("#agentRunHistory");
  if (!state.agentRuns.length) {
    list.innerHTML = renderEmptyState("暂无 Agent 运行记录", "执行任务后会在这里保留工具调用轨迹。");
    return;
  }
  list.innerHTML = state.agentRuns
    .map((run) => {
      const canCancel = ["queued", "running", "cancel_requested"].includes(run.status);
      const canRetry = ["failed", "cancelled"].includes(run.status);
      const statusClass = ["blocked", "failed", "cancelled"].includes(run.status)
        ? "danger"
        : ["queued", "cancel_requested"].includes(run.status)
          ? "muted"
          : "";
      return `
        <div class="compact-item">
          <div class="panel-title">
            <strong>#${run.id} ${escapeHtml(run.goal)}</strong>
            <span class="badge ${statusClass}">${escapeHtml(toolStatusLabel(run.status))}</span>
          </div>
          <span>${escapeHtml(run.display_name || run.username || "当前用户")} · ${run.execution_mode === "async" ? "异步任务" : "同步运行"} · ${formatDate(run.created_at)} · ${(run.tool_calls || []).length} 步</span>
          <p class="log-answer-preview">${escapeHtml(run.final_answer || "")}</p>
          <div class="document-actions">
            <button class="ghost-btn small-btn" data-agent-run="${run.id}">查看轨迹</button>
            ${canCancel ? `<button class="ghost-btn small-btn" data-agent-cancel="${run.id}">取消</button>` : ""}
            ${canRetry ? `<button class="ghost-btn small-btn" data-agent-retry="${run.id}">重试</button>` : ""}
          </div>
        </div>
      `;
    })
    .join("");
}

function renderQaTrace(traceItems) {
  const list = $("#qaTraceList");
  if (!list) return;
  setText("#qaTraceCount", traceItems.length);
  if (!traceItems.length) {
    list.innerHTML = renderEmptyState("暂无决策轨迹", "完成一次问答后显示安全检查、权限范围、检索和生成过程。");
    return;
  }
  list.innerHTML = traceItems
    .map(
      (item, index) => `
        <div class="qa-trace-item">
          <div class="trace-step-index">${index + 1}</div>
          <div>
            <div class="tool-call-head">
              <strong>${escapeHtml(traceStageLabel(item.stage))}</strong>
              <span class="badge ${item.status === "blocked" ? "danger" : item.status === "empty" ? "muted" : ""}">${escapeHtml(toolStatusLabel(item.status))}</span>
            </div>
            <p>${escapeHtml(item.detail || "")}</p>
            <pre>${escapeHtml(formatToolPayload(item.metrics || {}))}</pre>
          </div>
        </div>
      `,
    )
    .join("");
}

function renderQaUsage(usage) {
  const grid = $("#qaUsageGrid");
  if (!grid) return;
  if (!usage) {
    setText("#qaUsageModel", "未生成");
    grid.innerHTML = renderEmptyState("暂无调用用量", "完成一次问答后显示 token 和成本估算。");
    return;
  }
  setText("#qaUsageModel", usage.model || "local-extractive");
  const generationLabels = {
    llm: "大模型生成",
    local_fallback: "本地降级",
    local_extractive: "本地抽取",
    blocked: "安全拦截",
  };
  const metrics = [
    ["生成方式", generationLabels[usage.generation_mode] || usage.generation_mode || "本地抽取"],
    ["Token 来源", usage.token_source === "provider" ? "模型返回" : "本地估算"],
    ["Prompt Tokens", usage.prompt_tokens || 0],
    ["Completion Tokens", usage.completion_tokens || 0],
    ["Total Tokens", usage.total_tokens || 0],
    ["估算成本", `$${Number(usage.estimated_cost_usd || 0).toFixed(6)}`],
  ];
  if (usage.fallback_reason && usage.generation_mode === "local_fallback") {
    metrics.push(["降级原因", usage.fallback_reason]);
  }
  grid.innerHTML = metrics
    .map(
      ([label, value]) => `
        <div class="usage-metric">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `,
    )
    .join("");
}

function traceStageLabel(stage) {
  return {
    security_check: "安全检查",
    permission_scope: "权限范围",
    retrieval: "知识检索",
    answer_generation: "答案生成",
  }[stage] || stage || "未知阶段";
}

function formatToolPayload(value) {
  if (value === undefined || value === null) return "{}";
  return JSON.stringify(value, null, 2);
}

function toolStatusLabel(status) {
  return {
    queued: "排队中",
    running: "运行中",
    cancel_requested: "取消中",
    cancelled: "已取消",
    completed: "完成",
    passed: "通过",
    skipped: "跳过",
    blocked: "拦截",
    failed: "失败",
  }[status] || status || "未知";
}

async function loadUsers() {
  if (!hasPermission("users.manage")) return;
  const params = new URLSearchParams();
  const paging = state.pages.users;
  const q = ($("#userSearch")?.value || "").trim();
  const role = $("#userRoleFilter")?.value || "";
  const status = $("#userStatusFilter")?.value || "";
  if (q) params.set("q", q);
  if (role) params.set("role", role);
  if (status) params.set("status", status);
  params.set("page", paging.page);
  params.set("page_size", paging.pageSize);
  const result = await api(`/api/users?${params.toString()}`);
  state.users = result.items;
  paging.page = result.page;
  paging.pageSize = result.page_size;
  paging.total = result.total;
  renderPagination("#userPagination", "users", result);
  renderUsers();
}

function renderUsers() {
  const list = $("#userList");
  if (!state.users.length) {
    list.innerHTML = renderEmptyState("没有匹配用户", "创建用户或调整搜索、角色和状态筛选条件。");
    return;
  }
  list.innerHTML = state.users
    .map(
      (user) => `
        <div class="compact-item">
          <div class="panel-title">
            <strong>${escapeHtml(user.username)}</strong>
            <span class="badge ${user.is_active ? "" : "danger"}">${user.is_active ? "启用" : "禁用"}</span>
          </div>
          <span>${roleLabels[user.role] || "普通员工"} · ${formatDate(user.created_at)}</span>
          <div class="user-edit">
            <select class="input" data-user-role="${user.id}">
              <option value="employee" ${user.role === "employee" ? "selected" : ""}>普通员工</option>
              <option value="tech" ${user.role === "tech" ? "selected" : ""}>技术员工</option>
              <option value="admin" ${user.role === "admin" ? "selected" : ""}>管理员</option>
            </select>
            <select class="input" data-user-active="${user.id}">
              <option value="true" ${user.is_active ? "selected" : ""}>启用</option>
              <option value="false" ${!user.is_active ? "selected" : ""}>禁用</option>
            </select>
            <input class="input" data-user-password="${user.id}" type="password" placeholder="新密码，可留空" />
            <button class="ghost-btn small-btn" data-user-save="${user.id}">保存</button>
            <button class="delete-btn ${user.id === state.user?.id ? "hidden" : ""}" title="删除用户" data-user-delete="${user.id}">×</button>
          </div>
        </div>
      `,
    )
    .join("");
}

async function createUser() {
  setText("#userStatus", "正在创建...");
  try {
    await api("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({
        username: $("#newUsername").value.trim(),
        password: $("#newPassword").value,
        role: $("#newRole").value,
      }),
    });
    $("#newUsername").value = "";
    $("#newPassword").value = "";
    setText("#userStatus", "创建成功。");
    await loadUsers();
    await loadDashboard();
  } catch (error) {
    setText("#userStatus", error.message);
  }
}

async function saveUser(id) {
  const password = document.querySelector(`[data-user-password="${id}"]`)?.value || "";
  const payload = {
    role: document.querySelector(`[data-user-role="${id}"]`)?.value,
    is_active: document.querySelector(`[data-user-active="${id}"]`)?.value === "true",
  };
  if (password) payload.password = password;
  await api(`/api/users/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify(payload),
  });
  await loadUsers();
  await loadDashboard();
}

async function deleteUser(id) {
  const target = state.users.find((user) => String(user.id) === String(id));
  const name = target ? target.username : "该用户";
  if (!confirm(`确认删除 ${name}？删除后该账号将无法登录。`)) return;
  await api(`/api/users/${id}`, { method: "DELETE" });
  await loadUsers();
  await loadDashboard();
}

async function recheckKnowledgeGap(id) {
  const result = await api(`/api/knowledge-gaps/${id}/recheck`, { method: "POST" });
  alert(`复评完成：优化后质量分 ${percentText(result.after_score)}，状态 ${qualityLevelLabel(result.quality_level)}。`);
  await loadKnowledgeGaps();
  await loadDashboard();
}

async function downloadBatchReport(runId, format) {
  const response = await fetch(`/api/evaluation/batch/runs/${runId}/export?format=${format}`, {
    headers: { Authorization: `Bearer ${state.token}` },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "导出失败");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `batch_eval_run_${runId}.${format === "csv" ? "csv" : "md"}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function uploadSelectedFile() {
  if (!state.selectedFile) {
    setText("#uploadStatus", "请先选择一个文件。");
    return;
  }
  const form = new FormData();
  form.append("file", state.selectedFile);
  form.append("access_level", $("#accessLevelSelect").value);
  setText("#uploadStatus", "正在上传并建立索引...");
  $("#uploadBtn").disabled = true;
  try {
    const result = await api("/api/documents/upload", { method: "POST", body: form });
    setText("#uploadStatus", `入库成功：${accessLabels[result.access_level]} · ${result.chunk_count} 个知识片段`);
    $("#fileInput").value = "";
    state.selectedFile = null;
    await loadDocuments();
    await loadStats();
    await loadAnalytics();
  } catch (error) {
    setText("#uploadStatus", error.message);
  } finally {
    $("#uploadBtn").disabled = false;
  }
}

async function rebuildEmbeddings() {
  const button = $("#rebuildEmbeddingsBtn");
  button.disabled = true;
  setText("#embeddingRebuildStatus", "正在为缺失或过期文档重建向量索引...");
  try {
    const result = await api("/api/documents/embeddings/rebuild", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ force: false }),
    });
    setText(
      "#embeddingRebuildStatus",
      `向量索引完成：${result.indexed} 篇更新 · ${result.skipped} 篇跳过 · ${result.failed} 篇失败 · ${result.model}`,
    );
    await loadDocuments();
  } catch (error) {
    setText("#embeddingRebuildStatus", error.message);
  } finally {
    button.disabled = false;
  }
}

async function askQuestion() {
  const question = $("#questionInput").value.trim();
  if (!question) return;
  $("#askBtn").disabled = true;
  $("#answerBox").classList.add("loading");
  $("#answerBox").classList.remove("low-confidence");
  $("#answerBox").textContent = "正在检索知识库并生成回答...";
  state.currentLogId = null;
  $("#answerFeedback")?.classList.add("hidden");
  setText("#feedbackStatus", "");
  $("#citationList").innerHTML = "";
  setText("#citationCount", 0);
  renderQaTrace([]);
  renderQaUsage(null);
  if (managementRoles.has(state.user?.role)) {
    $("#confidenceBadge").className = "badge muted";
    $("#confidenceBadge").textContent = "生成中";
  }
  $("#securityHint").textContent = "";
  try {
    const result = await api("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ question, top_k: 5 }),
    });
    const confidence = Number(result.confidence || 0);
    state.currentLogId = result.log_id || null;
    $("#answerBox").textContent = result.answer;
    $("#answerFeedback")?.classList.toggle("hidden", !state.currentLogId);
    if (managementRoles.has(state.user?.role)) {
      $("#confidenceBadge").className = result.blocked ? "badge danger" : confidenceClass(result.confidence);
      $("#confidenceBadge").textContent = result.blocked ? "已拦截" : confidenceLabel(result.confidence);
      $("#lastConfidence").textContent = result.blocked ? "拦截" : confidenceLabel(result.confidence);
    }
    $("#answerBox").classList.toggle("low-confidence", !result.blocked && confidence < 0.18);
    renderQaTrace(result.agent_trace || []);
    renderQaUsage(result.usage || null);
    const lowConfidenceHint =
      managementRoles.has(state.user?.role)
        ? "置信度偏低：建议补充更明确的制度文档，或换一种更贴近原文的问法。"
        : "没有找到很明确的依据，可以换一种问法，或联系管理员补充资料。";
    $("#securityHint").textContent = result.block_reason || (!result.blocked && confidence < 0.18 ? lowConfidenceHint : "");
    if (managementRoles.has(state.user?.role)) {
      renderCitations(result.citations || []);
    }
    if (managementRoles.has(state.user?.role)) {
      await loadLogs();
      await loadStats();
      await loadAnalytics();
    } else {
      addSessionHistory(question, result.answer);
    }
  } catch (error) {
    $("#answerBox").textContent = error.message;
    if (managementRoles.has(state.user?.role)) {
      $("#confidenceBadge").className = "badge danger";
      $("#confidenceBadge").textContent = "失败";
    }
  } finally {
    $("#answerBox").classList.remove("loading");
    $("#askBtn").disabled = false;
  }
}

async function submitQaFeedback(rating) {
  if (!state.currentLogId) {
    setText("#feedbackStatus", "请先完成一次提问。");
    return;
  }
  const note =
    rating === "helpful"
      ? ""
      : rating === "unhelpful"
        ? "回答没有解决我的问题"
        : "需要补充更明确的资料";
  setText("#feedbackStatus", "正在提交反馈...");
  try {
    const result = await api("/api/qa-feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ log_id: state.currentLogId, rating, note }),
    });
    const message = result.gap_id ? `已反馈，并进入知识缺口 #${result.gap_id}` : "已反馈，谢谢。";
    setText("#feedbackStatus", message);
    if (managementRoles.has(state.user?.role)) {
      await Promise.all([loadDashboard(), state.route === "feedback" ? loadQaFeedbacks() : Promise.resolve()]);
    }
  } catch (error) {
    setText("#feedbackStatus", error.message);
  }
}

function addSessionHistory(question, answer) {
  state.sessionHistory = [{ question, answer, created_at: new Date().toISOString() }, ...state.sessionHistory].slice(0, 3);
  renderSessionHistory();
}

function renderSessionHistory() {
  const list = $("#sessionHistoryList");
  if (!list) return;
  if (!state.sessionHistory.length) {
    list.innerHTML = `<div class="empty">本次登录后的问答会显示在这里。</div>`;
    return;
  }
  list.innerHTML = state.sessionHistory
    .map(
      (item) => `
        <article class="session-history-item">
          <strong>${escapeHtml(item.question)}</strong>
          <p>${escapeHtml(item.answer)}</p>
          <span>${formatDate(item.created_at)}</span>
        </article>
      `,
    )
    .join("");
}

function clearSessionHistory() {
  state.sessionHistory = [];
  renderSessionHistory();
}

async function copyAnswer() {
  const text = $("#answerBox").textContent.trim();
  if (!text) {
    setText("#copyStatus", "暂无内容");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setText("#copyStatus", "已复制");
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
    setText("#copyStatus", "已复制");
  }
  window.setTimeout(() => setText("#copyStatus", ""), 1600);
}

function renderCitations(citations) {
  setText("#citationCount", citations.length);
  const list = $("#citationList");
  if (!citations.length) {
    list.innerHTML = renderEmptyState(
      "没有引用片段",
      "本次回答没有找到可展示来源，建议联系管理员补充资料后再提问。",
      managementRoles.has(state.user?.role) ? "去文档管理" : "",
      "documents",
    );
    return;
  }
  list.innerHTML = citations
    .map(
      (item, index) => `
        <article class="citation-item citation-card">
          <div class="citation-head">
            <strong>${escapeHtml(item.document_title)}</strong>
            <span class="badge muted">${index + 1}</span>
          </div>
          <span>片段 #${item.chunk_index + 1} · 相似度 ${Math.round(item.score * 100)}%</span>
          <p>${escapeHtml(item.content)}</p>
          <div class="compact-actions">
            <button class="ghost-btn small-btn" data-citation-toggle>展开</button>
            ${managementRoles.has(state.user?.role) ? `<button class="ghost-btn small-btn" data-citation-open="${item.document_id}">查看片段</button>` : ""}
          </div>
        </article>
      `,
    )
    .join("");
}

async function evaluateQuestion() {
  const question = $("#evalQuestion").value.trim();
  const keywords = splitInput("#evalKeywords");
  const expectedDocuments = splitInput("#evalDocuments");
  if (!question) {
    setText("#evalResult", "请填写评测问题。");
    return;
  }
  setText("#evalResult", "正在评测...");
  try {
    const result = await api("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ question, expected_keywords: keywords, expected_documents: expectedDocuments }),
    });
    setText("#evalResult", `评测得分：${percentText(result.score)} · 引用命中：${percentText(result.citation_hit)}`);
    await refreshEvaluationPage();
    await loadLogs();
  } catch (error) {
    setText("#evalResult", error.message);
  }
}

async function runBatchEvaluation() {
  $("#batchEvaluateBtn").disabled = true;
  setText("#evalResult", "正在运行版本化 RAG 质量门禁...");
  try {
    const result = await api("/api/evaluation/batch/run", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({}),
    });
    setText(
      "#evalResult",
      `${result.gate.status === "passed" ? "门禁通过" : `门禁失败：${result.gate.failed_metrics.map((metric) => evaluationMetricLabels[metric] || metric).join("、")}`} · ${result.summary.total} 条 · Recall@K ${percentText(result.summary.recall_at_k)} · MRR ${Number(result.summary.mrr || 0).toFixed(3)} · 答案正确率 ${percentText(result.summary.answer_accuracy)} · 拒答准确率 ${percentText(result.summary.abstention_accuracy)}`,
    );
    await refreshEvaluationPage();
    await loadLogs();
    await loadDashboard();
  } catch (error) {
    setText("#evalResult", error.message);
  } finally {
    $("#batchEvaluateBtn").disabled = false;
  }
}

async function deleteDocument(id) {
  await api(`/api/documents/${id}`, { method: "DELETE" });
  await loadDocuments();
  await loadStats();
  await loadAnalytics();
  setText("#chunkCountBadge", "未选择文档");
  $("#documentDetail").innerHTML = `<div class="empty">在文档资产中选择“片段”查看切分结果。</div>`;
  $("#documentVersions").innerHTML = `<div class="empty">在文档资产中选择“版本”查看变更历史。</div>`;
}

async function saveDocument(id) {
  const title = document.querySelector(`[data-title="${id}"]`)?.value.trim();
  const accessLevel = document.querySelector(`[data-access="${id}"]`)?.value;
  await api(`/api/documents/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ title, access_level: accessLevel }),
  });
  await loadDocuments();
  await loadDocumentVersions(id);
  await loadStats();
  await loadAnalytics();
}

async function reindexDocument(id) {
  const button = document.querySelector(`[data-reindex="${id}"]`);
  if (button) button.disabled = true;
  try {
    await api(`/api/documents/${id}/reindex`, { method: "POST" });
    await loadDocuments();
    await loadStats();
    if ($("#documentDetail").textContent.trim()) await loadDocumentChunks(id);
    await loadDocumentVersions(id);
  } finally {
    if (button) button.disabled = false;
  }
}

function splitInput(selector) {
  return $(selector)
    .value.split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function splitValue(value) {
  return String(value)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatCompactNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value || 0));
}

function percentText(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function bindEvents() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => switchRoute(button.dataset.route)));
  $("#mobileNavToggle").addEventListener("click", () => {
    const expanded = $("#mobileNavToggle").getAttribute("aria-expanded") === "true";
    setMobileNavExpanded(!expanded);
  });
  $("#loginForm").addEventListener("submit", (event) => {
    event.preventDefault();
    login();
  });
  $("#logoutBtn").addEventListener("click", logoutUser);
  $("#adminTopLogoutBtn").addEventListener("click", logoutUser);
  $("#employeeLogoutBtn").addEventListener("click", logoutUser);
  $("#forgotPasswordBtn").addEventListener("click", showForgotPasswordHint);
  $("#rememberLogin").addEventListener("change", () => {
    if (!$("#rememberLogin").checked) localStorage.removeItem(REMEMBER_LOGIN_KEY);
  });
  $("#fileInput").addEventListener("change", (event) => {
    state.selectedFile = event.target.files[0] || null;
    setText("#uploadStatus", state.selectedFile ? `已选择：${state.selectedFile.name}` : "");
  });
  $("#uploadBtn").addEventListener("click", uploadSelectedFile);
  $("#rebuildEmbeddingsBtn").addEventListener("click", rebuildEmbeddings);
  $("#askBtn").addEventListener("click", askQuestion);
  $("#runAgentBtn").addEventListener("click", runAgentFromWorkspace);
  $("#cancelAgentBtn").addEventListener("click", cancelActiveAgentRun);
  $("#refreshAgentRunsBtn").addEventListener("click", loadAgentRuns);
  $("#copyAnswerBtn").addEventListener("click", copyAnswer);
  $("#clearSessionHistoryBtn").addEventListener("click", clearSessionHistory);
  $$("[data-quick-question]").forEach((button) => {
    button.addEventListener("click", async () => {
      $("#questionInput").value = button.dataset.quickQuestion;
      await askQuestion();
    });
  });
  $$("[data-agent-goal]").forEach((button) => {
    button.addEventListener("click", () => {
      $("#agentGoalInput").value = button.dataset.agentGoal;
    });
  });
  $("#questionInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) askQuestion();
  });
  $("#refreshDocsBtn").addEventListener("click", loadDocuments);
  ["#docSearch", "#docAccessFilter", "#docTypeFilter", "#docSort"].forEach((selector) => {
    const node = $(selector);
    node.addEventListener(node.tagName === "INPUT" ? "input" : "change", () => {
      state.pages.documents.page = 1;
      loadDocuments();
    });
  });
  $("#refreshLogsBtn").addEventListener("click", loadLogs);
  $("#clearLogsBtn").addEventListener("click", clearLogs);
  $("#refreshGapsBtn").addEventListener("click", loadKnowledgeGaps);
  $("#refreshHealthBtn").addEventListener("click", loadKnowledgeHealth);
  $("#exportHealthMdBtn").addEventListener("click", () => downloadHealthReport("md"));
  $("#exportHealthCsvBtn").addEventListener("click", () => downloadHealthReport("csv"));
  $("#refreshFeedbackBtn").addEventListener("click", loadQaFeedbacks);
  $("#gapStatusFilter").addEventListener("change", loadKnowledgeGaps);
  $("#createGapFromQuestionBtn").addEventListener("click", createGapFromCurrentQuestion);
  $("#refreshEvaluationsBtn").addEventListener("click", refreshEvaluationPage);
  $("#refreshQualityBtn")?.addEventListener("click", loadQualityAssessments);
  $("#qualitySearch")?.addEventListener("input", () => {
    state.pages.quality.page = 1;
    loadQualityAssessments();
  });
  $("#qualityLevelFilter")?.addEventListener("change", () => {
    state.pages.quality.page = 1;
    loadQualityAssessments();
  });
  $("#refreshCasesBtn").addEventListener("click", loadEvaluationCases);
  $("#createCaseBtn").addEventListener("click", createEvaluationCase);
  $("#evaluateBtn").addEventListener("click", evaluateQuestion);
  $("#batchEvaluateBtn").addEventListener("click", runBatchEvaluation);
  $("#createUserBtn").addEventListener("click", createUser);
  $("#refreshUsersBtn").addEventListener("click", loadUsers);
  $("#userSearch").addEventListener("input", () => {
    state.pages.users.page = 1;
    loadUsers();
  });
  $("#userRoleFilter").addEventListener("change", () => {
    state.pages.users.page = 1;
    loadUsers();
  });
  $("#userStatusFilter").addEventListener("change", () => {
    state.pages.users.page = 1;
    loadUsers();
  });
  $("#refreshRolesBtn")?.addEventListener("click", loadRolePermissions);
  $("#saveRolesBtn")?.addEventListener("click", saveRolePermissions);
  document.body.addEventListener("click", async (event) => {
    const pageButton = event.target.closest("[data-page-resource]");
    if (pageButton && !pageButton.disabled) {
      await changePage(pageButton.dataset.pageResource, Number(pageButton.dataset.page));
      return;
    }
    const retryButton = event.target.closest("[data-quality-retry]");
    if (retryButton) await retryQualityAssessment(retryButton.dataset.qualityRetry);
  });
  $("#retrievalBtn").addEventListener("click", runRetrieval);
  $("#retrievalQuery").addEventListener("keydown", (event) => {
    if (event.key === "Enter") runRetrieval();
  });
  $("#documentList").addEventListener("click", async (event) => {
    const deleteId = event.target.dataset.delete;
    const viewId = event.target.dataset.view;
    const versionsId = event.target.dataset.versions;
    const saveId = event.target.dataset.save;
    const reindexId = event.target.dataset.reindex;
    if (deleteId) await deleteDocument(deleteId);
    if (viewId) await loadDocumentChunks(viewId);
    if (versionsId) await loadDocumentVersions(versionsId);
    if (saveId) await saveDocument(saveId);
    if (reindexId) await reindexDocument(reindexId);
  });
  $("#citationList").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.citationToggle !== undefined) {
      const card = button.closest(".citation-item");
      const expanded = card.classList.toggle("expanded");
      button.textContent = expanded ? "收起" : "展开";
    }
    if (button.dataset.citationOpen) {
      switchRoute("documents");
      await loadDocumentChunks(button.dataset.citationOpen);
      $("#documentDetail").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  $("#userList").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    const saveId = button.dataset.userSave;
    const deleteId = button.dataset.userDelete;
    if (saveId) await saveUser(saveId);
    if (deleteId) await deleteUser(deleteId);
  });
  $("#dashLowConfidence").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button?.dataset.gapQuestion) return;
    await createKnowledgeGap(button.dataset.gapQuestion, button.dataset.gapLog || null);
  });
  $("#answerFeedback").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button?.dataset.feedbackRating) return;
    await submitQaFeedback(button.dataset.feedbackRating);
  });
  $("#feedbackList").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button?.dataset.feedbackQuestion) return;
    await createKnowledgeGap(button.dataset.feedbackQuestion, button.dataset.feedbackLog || null);
    await loadQaFeedbacks();
  });
  $("#agentRunHistory").addEventListener("click", async (event) => {
    const cancelButton = event.target.closest("[data-agent-cancel]");
    if (cancelButton) {
      const runId = Number(cancelButton.dataset.agentCancel);
      state.activeAgentRunId = runId;
      await cancelActiveAgentRun();
      await monitorAgentRun(runId);
      return;
    }
    const retryButton = event.target.closest("[data-agent-retry]");
    if (retryButton) {
      await retryAgentRun(Number(retryButton.dataset.agentRetry));
      return;
    }
    const viewButton = event.target.closest("[data-agent-run]");
    if (!viewButton) return;
    const run = state.agentRuns.find((item) => String(item.id) === String(viewButton.dataset.agentRun));
    if (run) renderAgentResult({ run_id: run.id, ...run });
  });
  $("#healthLowConfidence").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button?.dataset.gapQuestion) return;
    await createKnowledgeGap(button.dataset.gapQuestion, button.dataset.gapLog || null);
    await loadKnowledgeHealth();
  });
  $("#healthDocuments").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button?.dataset.healthDocument) return;
    switchRoute("documents");
    await loadDocumentChunks(button.dataset.healthDocument);
    $("#documentDetail").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("#gapList").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    const saveId = button.dataset.gapSave;
    const resolveId = button.dataset.gapResolve;
    const recheckId = button.dataset.gapRecheck;
    const deleteId = button.dataset.gapDelete;
    if (saveId) await saveKnowledgeGap(saveId);
    if (recheckId) await recheckKnowledgeGap(recheckId);
    if (resolveId) await saveKnowledgeGap(resolveId, "resolved");
    if (deleteId) await deleteKnowledgeGap(deleteId);
  });
  $("#caseList").addEventListener("click", async (event) => {
    const saveId = event.target.dataset.caseSave;
    const deleteId = event.target.dataset.caseDelete;
    if (saveId) await saveEvaluationCase(saveId);
    if (deleteId) await deleteEvaluationCase(deleteId);
  });
  $("#refreshAuditBtn").addEventListener("click", loadAuditLogs);
  $("#clearAuditBtn").addEventListener("click", clearAuditLogs);
  $("#batchRunList").addEventListener("click", async (event) => {
    const mdId = event.target.dataset.exportMd;
    const csvId = event.target.dataset.exportCsv;
    if (mdId) await downloadBatchReport(mdId, "md");
    if (csvId) await downloadBatchReport(csvId, "csv");
  });
  document.addEventListener("click", (event) => {
    const route = event.target?.dataset?.emptyRoute;
    if (route) switchRoute(route);
  });
  window.addEventListener("hashchange", () => {
    const route = (location.hash || "#qa").replace("#", "");
    if (route !== state.route) switchRoute(route);
  });
}

bindEvents();
restoreSession();
