"""SQLite schema v1 — 初始迁移。

约定：
- events 表 append-only（触发器强制拒绝 UPDATE/DELETE，测试覆盖）；
- 外键开启（连接层 PRAGMA）；
- 所有时间戳 UTC ISO-8601 字符串；
- providers 表只存 api_key_ref（凭据引用），永不存明文 key。
"""

SCHEMA_V1 = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    profile TEXT NOT NULL DEFAULT 'standard',
    created_at TEXT NOT NULL,
    settings_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    status TEXT NOT NULL,
    profile TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE stages (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    key TEXT NOT NULL,
    status TEXT NOT NULL,
    UNIQUE(run_id, key)
);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    stage_key TEXT NOT NULL,
    node_key TEXT NOT NULL,
    role_id TEXT,
    kind TEXT NOT NULL DEFAULT 'agent',
    status TEXT NOT NULL,
    owner_token TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    expected_artifacts_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id, node_key)
);

CREATE TABLE task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(id),
    depends_on TEXT NOT NULL REFERENCES tasks(id),
    PRIMARY KEY (task_id, depends_on)
);

CREATE TABLE agent_invocations (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    role_id TEXT NOT NULL,
    provider_profile TEXT NOT NULL,
    model TEXT NOT NULL,
    reasoning TEXT,
    context_manifest_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    usage_json TEXT
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invocation_id TEXT NOT NULL REFERENCES agent_invocations(id),
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    UNIQUE(invocation_id, seq)
);

CREATE TABLE tool_calls (
    id TEXT PRIMARY KEY,
    invocation_id TEXT NOT NULL REFERENCES agent_invocations(id),
    seq INTEGER NOT NULL,
    name TEXT NOT NULL,
    args_json TEXT NOT NULL,
    result_json TEXT,
    status TEXT NOT NULL,
    error TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    UNIQUE(invocation_id, seq)
);

CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    rel_path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'json',
    schema_id TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    hash TEXT NOT NULL,
    sealed_path TEXT,
    producer_task TEXT,
    input_versions_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(task_id, rel_path, version)
);

CREATE TABLE contracts (
    schema_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    producer TEXT NOT NULL,
    schema_json TEXT NOT NULL
);

CREATE TABLE issues (
    id TEXT PRIMARY KEY,
    ledger TEXT NOT NULL,
    external_id TEXT,
    severity TEXT NOT NULL DEFAULT '叙述',
    target TEXT NOT NULL DEFAULT '文',
    location TEXT NOT NULL DEFAULT '',
    problem TEXT NOT NULL DEFAULT '',
    instruction TEXT NOT NULL DEFAULT '',
    acceptance TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    round INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    reopen_count INTEGER NOT NULL DEFAULT 0,
    related_questions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_issues_ledger_status ON issues(ledger, status);

CREATE TABLE issue_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL REFERENCES issues(id),
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE checkpoints (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    tag TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, tag)
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT,
    task_id TEXT,
    invocation_id TEXT,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TRIGGER events_no_update
    BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events is append-only');
END;

CREATE TRIGGER events_no_delete
    BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events is append-only');
END;

CREATE TABLE providers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    protocol TEXT NOT NULL,
    base_url TEXT NOT NULL,
    api_key_ref TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE model_profiles (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL REFERENCES providers(id),
    model TEXT NOT NULL,
    reasoning TEXT,
    max_output_tokens INTEGER,
    timeout_s INTEGER,
    extra_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invocation_id TEXT REFERENCES agent_invocations(id),
    input_tokens INTEGER,
    output_tokens INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
