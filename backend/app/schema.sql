CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    access_level TEXT NOT NULL DEFAULT 'internal',
    status TEXT NOT NULL DEFAULT 'ready',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    embedding_status TEXT NOT NULL DEFAULT 'not_configured',
    embedding_model TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_json TEXT NOT NULL,
    embedding_json TEXT NOT NULL DEFAULT '[]',
    embedding_model TEXT,
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS qa_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    confidence REAL NOT NULL,
    blocked INTEGER NOT NULL DEFAULT 0,
    block_reason TEXT,
    user_id INTEGER,
    citations_json TEXT NOT NULL,
    agent_trace_json TEXT NOT NULL DEFAULT '[]',
    usage_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    expected_keywords TEXT NOT NULL,
    expected_documents TEXT NOT NULL DEFAULT '[]',
    answer TEXT NOT NULL,
    score REAL NOT NULL,
    citation_hit REAL NOT NULL DEFAULT 0,
    user_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'employee',
    display_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    permission_code TEXT NOT NULL,
    is_allowed INTEGER NOT NULL DEFAULT 0,
    updated_by INTEGER,
    updated_at TEXT NOT NULL,
    UNIQUE(role, permission_code),
    FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS evaluation_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    expected_keywords TEXT NOT NULL,
    expected_documents TEXT NOT NULL,
    should_answer INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    total INTEGER NOT NULL,
    avg_score REAL NOT NULL,
    avg_confidence REAL NOT NULL,
    citation_hit_rate REAL NOT NULL,
    recall_at_k REAL NOT NULL DEFAULT 0,
    mrr REAL NOT NULL DEFAULT 0,
    answer_accuracy REAL NOT NULL DEFAULT 0,
    abstention_accuracy REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS batch_eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    case_id INTEGER,
    question TEXT NOT NULL,
    expected_keywords TEXT NOT NULL,
    expected_documents TEXT NOT NULL,
    answer TEXT NOT NULL,
    score REAL NOT NULL,
    confidence REAL NOT NULL,
    citation_hit REAL NOT NULL,
    should_answer INTEGER NOT NULL DEFAULT 1,
    retrieval_recall REAL,
    reciprocal_rank REAL,
    answer_correct INTEGER NOT NULL DEFAULT 0,
    abstention_correct INTEGER NOT NULL DEFAULT 0,
    citations_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES batch_eval_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(case_id) REFERENCES evaluation_cases(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    source_log_id INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    note TEXT NOT NULL DEFAULT '',
    created_by INTEGER,
    assigned_to INTEGER,
    resolution_action TEXT NOT NULL DEFAULT '',
    before_score REAL,
    after_score REAL,
    review_answer TEXT,
    review_citations_json TEXT NOT NULL DEFAULT '[]',
    reviewed_by INTEGER,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY(source_log_id) REFERENCES qa_logs(id) ON DELETE SET NULL,
    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY(assigned_to) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS qa_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id INTEGER NOT NULL,
    rating TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_by INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(log_id, created_by),
    FOREIGN KEY(log_id) REFERENCES qa_logs(id) ON DELETE CASCADE,
    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS qa_quality_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id INTEGER NOT NULL UNIQUE,
    confidence_score REAL NOT NULL,
    top_similarity_score REAL NOT NULL,
    citation_score REAL NOT NULL,
    feedback_score REAL NOT NULL,
    quality_score REAL NOT NULL,
    quality_level TEXT NOT NULL,
    risk_reasons TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'completed',
    error_message TEXT,
    assessed_at TEXT NOT NULL,
    FOREIGN KEY(log_id) REFERENCES qa_logs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    final_answer TEXT NOT NULL,
    user_id INTEGER,
    tool_calls_json TEXT NOT NULL DEFAULT '[]',
    plan_json TEXT NOT NULL DEFAULT '{}',
    planner_mode TEXT NOT NULL DEFAULT 'deterministic',
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    execution_mode TEXT NOT NULL DEFAULT 'sync',
    top_k INTEGER NOT NULL DEFAULT 5,
    idempotency_key TEXT,
    parent_run_id INTEGER,
    cancel_requested_at TEXT,
    updated_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY(parent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS document_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    action TEXT NOT NULL,
    title TEXT NOT NULL,
    access_level TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
);
