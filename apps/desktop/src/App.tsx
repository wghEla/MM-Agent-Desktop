import React, { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

import {
  backend,
  type Dashboard,
  type ProjectView,
  type ProviderProfile,
  type RunStatus,
} from "./api";
import { ArtifactViewer, ImportPanel } from "./WorkspacePanels";
import { StageRail } from "./StageRail";

const pickFolderDialog = () =>
  openDialog({ directory: true, multiple: false, title: "选择工作区文件夹" });

const protocolDefaults: Record<string, string> = {
  openai_chat: "https://api.openai.com/v1",
  openai_responses: "https://api.openai.com/v1",
  anthropic_messages: "https://api.anthropic.com",
  gemini: "https://generativelanguage.googleapis.com",
  openai_compatible: "",
};

type RecentWorkspace = {
  root: string;
  name: string;
  profile: string;
  lastOpened: number;
};

const RECENT_WORKSPACES_KEY = "mmagent.recentWorkspaces";

function loadRecentWorkspaces(): RecentWorkspace[] {
  try {
    const raw = window.localStorage.getItem(RECENT_WORKSPACES_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item) => item && typeof item.root === "string" && typeof item.name === "string")
      .slice(0, 8);
  } catch {
    return [];
  }
}

const providerPresets = [
  { id: "openai", label: "OpenAI", protocol: "openai_responses", baseUrl: "https://api.openai.com/v1" },
  { id: "anthropic", label: "Anthropic", protocol: "anthropic_messages", baseUrl: "https://api.anthropic.com" },
  { id: "gemini", label: "Gemini", protocol: "gemini", baseUrl: "https://generativelanguage.googleapis.com" },
  { id: "groq", label: "Groq", protocol: "openai_compatible", baseUrl: "https://api.groq.com/openai/v1" },
  { id: "deepseek", label: "DeepSeek", protocol: "openai_compatible", baseUrl: "https://api.deepseek.com" },
  { id: "zcode", label: "ZCode", protocol: "openai_compatible", baseUrl: "" },
  { id: "compatible", label: "OpenAI Compatible", protocol: "openai_compatible", baseUrl: "" },
] as const;

function App() {
  const [project, setProject] = useState<ProjectView | null>(null);
  const [providers, setProviders] = useState<ProviderProfile[]>([]);
  const [selectedProvider, setSelectedProvider] = useState("");
  const [run, setRun] = useState<RunStatus | null>(null);
  const [runHistory, setRunHistory] = useState<RunStatus[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [recentWorkspaces, setRecentWorkspaces] = useState<RecentWorkspace[]>(loadRecentWorkspaces);

  const selected = useMemo(
    () => providers.find((item) => item.model_profile_id === selectedProvider) ?? null,
    [providers, selectedProvider],
  );

  const refreshProviders = useCallback(async (p: ProjectView) => {
    const list = await backend<ProviderProfile[]>("GET", `/projects/${p.id}/providers`);
    setProviders(list);
    setSelectedProvider((current) =>
      current && list.some((item) => item.model_profile_id === current)
        ? current
        : (list[0]?.model_profile_id ?? ""),
    );
  }, []);

  const refreshRun = useCallback(async () => {
    if (!project || !run) return;
    const [status, board] = await Promise.all([
      backend<RunStatus>("GET", `/projects/${project.id}/runs/${run.id}`),
      backend<Dashboard>("GET", `/projects/${project.id}/runs/${run.id}/dashboard`),
    ]);
    setRun(status);
    setRunHistory((items) => items.map((item) => item.id === status.id ? status : item));
    setDashboard(board);
  }, [project, run?.id]);

  useEffect(() => {
    if (!run || !project) return;
    void refreshRun().catch((err) => setError(String(err)));
    if (!["RUNNING", "PAUSED"].includes(run.status)) return;
    const timer = window.setInterval(() => {
      void refreshRun().catch((err) => setError(String(err)));
    }, 1800);
    return () => window.clearInterval(timer);
  }, [project?.id, run?.id, run?.status, refreshRun]);

  async function loadRunHistory(p: ProjectView, selectExisting = false) {
    const history = await backend<RunStatus[]>("GET", `/projects/${p.id}/runs`);
    setRunHistory(history);
    if (!selectExisting) return;
    const candidate = history.find((item) => ["RUNNING", "PAUSED"].includes(item.status)) ?? history[0] ?? null;
    setRun(candidate);
    if (candidate) {
      const board = await backend<Dashboard>("GET", `/projects/${p.id}/runs/${candidate.id}/dashboard`);
      setDashboard(board);
    } else {
      setDashboard(null);
    }
  }

  async function selectHistoricalRun(candidate: RunStatus) {
    if (!project) return;
    await guarded(async () => {
      setRun(candidate);
      const board = await backend<Dashboard>("GET", `/projects/${project.id}/runs/${candidate.id}/dashboard`);
      setDashboard(board);
    });
  }

  async function guarded(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function createOrOpen(mode: "create" | "open", root: string, name: string, profile: string) {
    await guarded(async () => {
      const p = mode === "create"
        ? await backend<ProjectView>("POST", "/projects", { root, name, profile })
        : await backend<ProjectView>("POST", "/projects/open", { root });
      setProject(p);
      setRecentWorkspaces((current) => {
        const next = [
          { root: p.root_path, name: p.name, profile: p.profile, lastOpened: Date.now() },
          ...current.filter((item) => item.root !== p.root_path),
        ].slice(0, 8);
        window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify(next));
        return next;
      });
      setRun(null);
      setRunHistory([]);
      setDashboard(null);
      await refreshProviders(p);
      await loadRunHistory(p, mode === "open");
      setNotice(mode === "create" ? "项目已创建" : "项目已打开");
    });
  }

  async function startRun(profile: string) {
    if (!project || !selectedProvider) return;
    await guarded(async () => {
      const result = await backend<{ run_id: string }>("POST", `/projects/${project.id}/runs`, {
        model_profile_id: selectedProvider,
        profile,
      });
      const status = await backend<RunStatus>("GET", `/projects/${project.id}/runs/${result.run_id}`);
      setRun(status);
      setDashboard(null);
      await loadRunHistory(project);
      setNotice("运行已启动");
    });
  }

  async function control(kind: "pause" | "resume" | "cancel") {
    if (!project || !run) return;
    await guarded(async () => {
      const body =
        kind === "resume"
          ? { model_profile_id: selectedProvider }
          : kind === "cancel"
            ? { reason: "user cancelled from desktop" }
            : undefined;
      await backend("POST", `/projects/${project.id}/runs/${run.id}/${kind}`, body);
      await refreshRun();
      await loadRunHistory(project);
      setNotice(kind === "pause" ? "已请求暂停" : kind === "resume" ? "已继续" : "已请求取消");
    });
  }

  return (
    <div className="app-shell ui-v2">
      <header className="topbar">
        <div className="brand compact">
          <div className="brand-mark" aria-hidden="true">M</div>
          <div>
            <h1>MM-Agent</h1>
            <p>数学建模智能工作台</p>
          </div>
        </div>

        <div className="topbar-context">
          {project ? (
            <>
              <strong>{project.name}</strong>
              <span className="context-separator">/</span>
              <span>{selected?.model || "未配置模型"}</span>
              <span className="context-separator">/</span>
              <span>{run?.status || "Ready"}</span>
            </>
          ) : (
            <span>选择工作区开始</span>
          )}
        </div>

        <button className="icon-button settings-button" onClick={() => setSettingsOpen(true)}>
          <span aria-hidden="true">⚙</span>
          设置
        </button>
      </header>

      <div className="workspace-layout">
        <aside className="workspace-sidebar">
          <div className="sidebar-section-title">WORKSPACE</div>
          {!project ? (
            <ProjectPanel
              project={project}
              busy={busy}
              onSubmit={createOrOpen}
            />
          ) : (
            <>
              <WorkspaceSummary
                project={project}
                onSwitch={() => {
                  setProject(null);
                  setProviders([]);
                  setSelectedProvider("");
                  setRun(null);
                  setRunHistory([]);
                  setDashboard(null);
                }}
              />
              <ImportPanel project={project} />

              {runHistory.length > 0 && (
                <RunHistoryPanel
                  runs={runHistory}
                  currentRunId={run?.id ?? null}
                  busy={busy}
                  onSelect={selectHistoricalRun}
                  onNew={() => {
                    setRun(null);
                    setDashboard(null);
                  }}
                />
              )}
            </>
          )}

          <div className="sidebar-spacer" />

          <button className="sidebar-settings" onClick={() => setSettingsOpen(true)}>
            <span aria-hidden="true">⚙</span>
            Models & Providers
            {providers.length > 0 && <span className="count-badge">{providers.length}</span>}
          </button>
        </aside>

        <main className="workbench-main">
          {!project ? (
            <WelcomeSurface
              recent={recentWorkspaces}
              busy={busy}
              onOpen={(workspace) => createOrOpen("open", workspace.root, workspace.name, workspace.profile)}
            />
          ) : (
            <>
              <div className="workbench-toolbar">
                <div className="toolbar-provider">
                  <span className="toolbar-label">MODEL</span>
                  {providers.length > 0 ? (
                    <select
                      value={selectedProvider}
                      onChange={(event) => setSelectedProvider(event.target.value)}
                      aria-label="当前模型"
                    >
                      {providers.map((item) => (
                        <option key={item.model_profile_id} value={item.model_profile_id}>
                          {item.name} · {item.model}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <button onClick={() => setSettingsOpen(true)}>配置 Provider</button>
                  )}
                </div>

                <RunToolbar
                  provider={selected}
                  run={run}
                  busy={busy}
                  onStart={startRun}
                  onControl={control}
                />
              </div>

              <StageRail dashboard={dashboard} />

              {notice && <div className="notice-banner success">{notice}</div>}
              {error && <div className="notice-banner error">{error}</div>}

              <div className="pipeline-surface">
                {!run ? (
                  <div className="workbench-empty">
                    <div className="empty-kicker">WORKSPACE READY</div>
                    <h2>材料准备完成后，从这里启动一次建模运行。</h2>
                    <p>
                      当前工作区：<span className="mono">{project.root_path}</span>
                    </p>
                    <p>Provider 配置、历史运行与交付物分别位于顶部、左侧和右侧，不再挤在同一个控制栏里。</p>
                  </div>
                ) : (
                  <DashboardView run={run} dashboard={dashboard} onRefresh={() => void refreshRun()} />
                )}
              </div>
            </>
          )}
        </main>

        <aside className="artifact-dock">
          <div className="sidebar-section-title">ARTIFACTS</div>
          {project ? (
            <ArtifactViewer project={project} />
          ) : (
            <div className="dock-empty">打开工作区后，这里会显示论文、图表、结果、审稿与交付物。</div>
          )}
        </aside>
      </div>

      {settingsOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setSettingsOpen(false)}>
          <div className="settings-modal" role="dialog" aria-modal="true" aria-label="Models & Providers" onMouseDown={(event) => event.stopPropagation()}>
            <div className="settings-header">
              <div>
                <span className="eyebrow">SETTINGS</span>
                <h2>Models & Providers</h2>
                <p>模型配置与凭据独立于主工作台；API Key 只进入系统凭据库。</p>
              </div>
              <button className="icon-button" onClick={() => setSettingsOpen(false)} aria-label="关闭设置">×</button>
            </div>

            {!project ? (
              <div className="settings-empty">请先创建或打开工作区，再配置该项目使用的 Provider。</div>
            ) : (
              <ProviderPanel
                project={project}
                providers={providers}
                selectedProvider={selectedProvider}
                busy={busy}
                onSelect={setSelectedProvider}
                onRefresh={() => guarded(async () => refreshProviders(project))}
                onCreated={async () => {
                  await refreshProviders(project);
                  setNotice("Provider 已保存；密钥仅保存在 Windows Credential Manager");
                }}
                onGuarded={guarded}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function WorkspaceSummary({
  project,
  onSwitch,
}: {
  project: ProjectView;
  onSwitch: () => void;
}) {
  return (
    <section className="workspace-summary">
      <div className="workspace-icon" aria-hidden="true">Σ</div>
      <div className="workspace-summary-copy">
        <strong>{project.name}</strong>
        <span className="mono" title={project.root_path}>{project.root_path}</span>
        <span>{project.profile}档 · Runtime-owned workspace</span>
      </div>
      <button className="workspace-switch" onClick={onSwitch} title="切换工作区">↗</button>
    </section>
  );
}

function WelcomeSurface({
  recent,
  busy,
  onOpen,
}: {
  recent: RecentWorkspace[];
  busy: boolean;
  onOpen: (workspace: RecentWorkspace) => Promise<void>;
}) {
  return (
    <div className="welcome-surface">
      <div className="welcome-mark" aria-hidden="true">M</div>
      <span className="eyebrow">MM-AGENT DESKTOP</span>
      <h2>把题目、求解、审稿和最终论文放在一个可追踪的工作区里。</h2>
      <p>左侧创建或打开工作区。运行后，中间展示 S0–S6 / Gate 流程，右侧持续展示论文、图表和证据载体。</p>
      <div className="welcome-points">
        <span>SQLite durable state</span>
        <span>Fail-closed gates</span>
        <span>Frozen Truth</span>
      </div>

      {recent.length > 0 && (
        <div className="recent-workspaces">
          <div className="recent-heading">最近工作区</div>
          {recent.map((workspace) => (
            <button
              key={workspace.root}
              disabled={busy}
              className="recent-workspace"
              onClick={() => void onOpen(workspace)}
            >
              <span className="recent-workspace-icon">Σ</span>
              <span className="recent-workspace-copy">
                <strong>{workspace.name}</strong>
                <span className="mono">{workspace.root}</span>
              </span>
              <span className="recent-workspace-profile">{workspace.profile}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectPanel({
  project,
  busy,
  onSubmit,
}: {
  project: ProjectView | null;
  busy: boolean;
  onSubmit: (mode: "create" | "open", root: string, name: string, profile: string) => Promise<void>;
}) {
  const [root, setRoot] = useState("");
  const [name, setName] = useState("数学建模项目");
  const [profile, setProfile] = useState("标准");
  const [pickerError, setPickerError] = useState("");

  async function pickFolder() {
    setPickerError("");
    try {
      const picked = await pickFolderDialog();
      if (typeof picked === "string" && picked) {
        setRoot(picked);
        const folderName = picked.split(/[\\/]/).filter(Boolean).pop() ?? "";
        if (folderName && (!name.trim() || name === "数学建模项目")) {
          setName(folderName);
        }
      }
    } catch (err) {
      setPickerError(
        `原生文件夹选择器不可用（${err instanceof Error ? err.message : String(err)}）；请使用高级：手动路径。`,
      );
    }
  }

  return (
    <section className="card">
      <h2>项目</h2>
      {project && (
        <p className="muted mono">{project.root_path}</p>
      )}
      <button
        className="primary picker-button"
        disabled={busy}
        onClick={() => void pickFolder()}
      >
        浏览选择工作区文件夹…
      </button>
      {pickerError && <p className="error">{pickerError}</p>}
      {root && (
        <p className="muted mono picker-selected" title={root}>
          已选择：{root}
        </p>
      )}
      <div className="field">
        <label>项目名</label>
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label>档位</label>
        <select value={profile} onChange={(e) => setProfile(e.target.value)}>
          <option>快速</option>
          <option>标准</option>
          <option>深度</option>
        </select>
      </div>
      <div className="row">
        <button
          className="primary"
          disabled={busy || !root.trim() || !name.trim()}
          onClick={() => void onSubmit("create", root.trim(), name.trim(), profile)}
        >
          创建
        </button>
        <button
          disabled={busy || !root.trim()}
          onClick={() => void onSubmit("open", root.trim(), name.trim(), profile)}
        >
          打开
        </button>
      </div>
      <details className="advanced-settings">
        <summary>高级：手动路径</summary>
        <div className="advanced-body">
          <div className="field">
            <label>工作区路径</label>
            <input value={root} onChange={(e) => setRoot(e.target.value)} placeholder="D:\\MMProjects\\2026-C" />
          </div>
        </div>
      </details>
    </section>
  );
}

function ProviderPanel({
  project,
  providers,
  selectedProvider,
  busy,
  onSelect,
  onRefresh,
  onCreated,
  onGuarded,
}: {
  project: ProjectView;
  providers: ProviderProfile[];
  selectedProvider: string;
  busy: boolean;
  onSelect: (value: string) => void;
  onRefresh: () => void;
  onCreated: () => Promise<void>;
  onGuarded: (action: () => Promise<void>) => Promise<void>;
}) {
  const selected = providers.find((item) => item.model_profile_id === selectedProvider) ?? null;
  const [showCreate, setShowCreate] = useState(providers.length === 0);
  const [name, setName] = useState("Primary");
  const [protocol, setProtocol] = useState("openai_responses");
  const [baseUrl, setBaseUrl] = useState(protocolDefaults.openai_responses);
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [compatibleImageInput, setCompatibleImageInput] = useState(false);
  const [compatibleReasoningEffort, setCompatibleReasoningEffort] = useState(false);
  const [testResult, setTestResult] = useState("");

  function changeProtocol(value: string) {
    setProtocol(value);
    setBaseUrl(protocolDefaults[value] ?? "");
    if (value !== "openai_compatible") {
      setCompatibleImageInput(false);
      setCompatibleReasoningEffort(false);
    }
  }

  function applyPreset(preset: (typeof providerPresets)[number]) {
    setName(preset.label);
    setProtocol(preset.protocol);
    setBaseUrl(preset.baseUrl);
    setModel("");
    setReasoning("");
    setCompatibleImageInput(false);
    setCompatibleReasoningEffort(false);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    await onGuarded(async () => {
      await backend("POST", `/projects/${project.id}/providers`, {
        name,
        protocol,
        base_url: baseUrl,
        model,
        api_key: apiKey || null,
        reasoning: reasoning || null,
        timeout_s: 300,
        extra: protocol === "openai_compatible"
          ? {
              image_input: compatibleImageInput,
              reasoning_effort: compatibleReasoningEffort,
            }
          : {},
      });
      setApiKey("");
      setShowCreate(false);
      await onCreated();
    });
  }

  async function testSelected() {
    if (!selectedProvider) return;
    setTestResult("测试中…");
    try {
      const result = await backend<{ ok: boolean; detail: string }>(
        "POST",
        `/projects/${project.id}/providers/${selectedProvider}/test`,
      );
      setTestResult(`${result.ok ? "✓" : "✗"} ${result.detail}`);
    } catch (err) {
      setTestResult(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="provider-settings-grid">
      <aside className="provider-settings-list">
        <div className="provider-list-heading">
          <span>Providers</span>
          <button className="small-button" onClick={() => setShowCreate(true)}>＋</button>
        </div>

        {providers.map((item) => (
          <button
            key={item.model_profile_id}
            className={`provider-nav-item ${selectedProvider === item.model_profile_id && !showCreate ? "selected" : ""}`}
            onClick={() => {
              onSelect(item.model_profile_id);
              setShowCreate(false);
              setTestResult("");
            }}
          >
            <span className="provider-avatar">{item.name.slice(0, 1).toUpperCase()}</span>
            <span className="provider-nav-copy">
              <strong>{item.name}</strong>
              <span>{item.model}</span>
            </span>
            {item.has_api_key && <span className="credential-dot" title="API Key 已保存" />}
          </button>
        ))}

        <button
          className={`provider-nav-item add-provider ${showCreate ? "selected" : ""}`}
          onClick={() => setShowCreate(true)}
        >
          <span className="provider-avatar">＋</span>
          <span className="provider-nav-copy">
            <strong>添加 Provider</strong>
            <span>API Key / Compatible</span>
          </span>
        </button>
      </aside>

      <section className="provider-settings-detail">
        {showCreate || !selected ? (
          <form onSubmit={(e) => void submit(e)}>
            <div className="detail-heading">
              <div>
                <span className="eyebrow">NEW PROVIDER</span>
                <h3>添加模型渠道</h3>
                <p>选择常见渠道只会预填协议和 Endpoint；Runtime 仍使用现有适配器。</p>
              </div>
            </div>

            <div className="preset-grid">
              {providerPresets.map((preset) => (
                <button
                  type="button"
                  key={preset.id}
                  className="preset-button"
                  onClick={() => applyPreset(preset)}
                >
                  <span className="preset-mark">{preset.label.slice(0, 1)}</span>
                  <span>{preset.label}</span>
                </button>
              ))}
            </div>

            <div className="settings-section">
              <h4>Authentication</h4>
              <div className="field">
                <label>API Key</label>
                <input
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="仅写入 Windows Credential Manager"
                />
                <span className="field-hint">保存后不会在界面、SQLite 或日志中回显真实密钥。</span>
              </div>
            </div>

            <div className="settings-section two-column-fields">
              <div className="field">
                <label>名称</label>
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="field">
                <label>Model ID</label>
                <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="精确模型 ID" />
              </div>
            </div>

            <details className="advanced-settings">
              <summary>Advanced</summary>
              <div className="advanced-body">
                <div className="settings-section two-column-fields">
                  <div className="field">
                    <label>协议</label>
                    <select value={protocol} onChange={(e) => changeProtocol(e.target.value)}>
                      <option value="openai_responses">OpenAI Responses</option>
                      <option value="openai_chat">OpenAI Chat</option>
                      <option value="anthropic_messages">Anthropic Messages</option>
                      <option value="gemini">Gemini</option>
                      <option value="openai_compatible">OpenAI Compatible</option>
                    </select>
                  </div>
                  <div className="field">
                    <label>Reasoning</label>
                    <select value={reasoning} onChange={(e) => setReasoning(e.target.value)}>
                      <option value="">Provider 默认</option>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                      <option value="xhigh">xhigh</option>
                    </select>
                  </div>
                </div>
                <div className="field">
                  <label>Base URL</label>
                  <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" />
                </div>
                {protocol === "openai_compatible" && (
                  <div className="capability-options">
                    <label>
                      <input
                        type="checkbox"
                        checked={compatibleImageInput}
                        onChange={(e) => setCompatibleImageInput(e.target.checked)}
                      />
                      支持图片输入
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={compatibleReasoningEffort}
                        onChange={(e) => setCompatibleReasoningEffort(e.target.checked)}
                      />
                      支持 reasoning_effort
                    </label>
                  </div>
                )}
              </div>
            </details>

            <div className="settings-actions">
              <button
                className="primary"
                disabled={busy || !name.trim() || !baseUrl.trim() || !model.trim()}
              >
                保存 Provider
              </button>
            </div>
          </form>
        ) : (
          <>
            <div className="detail-heading provider-current-heading">
              <div>
                <span className="eyebrow">PROVIDER</span>
                <h3>{selected.name}</h3>
                <p className="mono">{selected.model}</p>
              </div>
              <button onClick={onRefresh} disabled={busy}>刷新</button>
            </div>

            <div className="provider-status-card">
              <div>
                <span className="status-kicker">Authentication</span>
                <strong>{selected.has_api_key ? "API Key 已保存" : "未保存 API Key"}</strong>
                <span>{selected.has_api_key ? "Windows Credential Manager" : "Keyless / local relay"}</span>
              </div>
              <span className={`credential-state ${selected.has_api_key ? "ok" : "neutral"}`}>
                {selected.has_api_key ? "Secure" : "Keyless"}
              </span>
            </div>

            <div className="provider-facts">
              <div>
                <span>Protocol</span>
                <strong>{selected.protocol}</strong>
              </div>
              <div>
                <span>Model</span>
                <strong className="mono">{selected.model}</strong>
              </div>
              <div className="wide">
                <span>Endpoint</span>
                <strong className="mono">{selected.base_url}</strong>
              </div>
              <div>
                <span>Reasoning</span>
                <strong>{selected.reasoning || "Provider default"}</strong>
              </div>
            </div>

            <div className="settings-actions test-connection-row">
              <button
                className="primary"
                onClick={() => void testSelected()}
                disabled={!selectedProvider || busy}
              >
                Test Connection
              </button>
              {testResult && <span className="test-result">{testResult}</span>}
            </div>

            <div className="settings-note">
              账号登录只会在厂商提供并明确允许第三方桌面应用使用的 OAuth / Device Flow 接入后出现；不会导入浏览器 Cookie 或复用其他客户端 Token。
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function RunHistoryPanel({
  runs,
  currentRunId,
  busy,
  onSelect,
  onNew,
}: {
  runs: RunStatus[];
  currentRunId: string | null;
  busy: boolean;
  onSelect: (run: RunStatus) => Promise<void>;
  onNew: () => void;
}) {
  return (
    <section className="card">
      <div className="provider-title">
        <h2>运行历史</h2>
        <button disabled={busy} onClick={onNew}>新建一炉</button>
      </div>
      <div className="run-history">
        {runs.map((item) => (
          <button
            key={item.id}
            disabled={busy}
            className={`run-history-item ${currentRunId === item.id ? "selected" : ""}`}
            onClick={() => void onSelect(item)}
          >
            <span className="mono">{item.id}</span>
            <span className={`status ${item.status}`}>{item.status}</span>
            <span className="muted">{item.profile}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function RunToolbar({
  provider,
  run,
  busy,
  onStart,
  onControl,
}: {
  provider: ProviderProfile | null;
  run: RunStatus | null;
  busy: boolean;
  onStart: (profile: string) => Promise<void>;
  onControl: (kind: "pause" | "resume" | "cancel") => Promise<void>;
}) {
  const [profile, setProfile] = useState("标准");

  return (
    <div className="run-toolbar">
      <select
        className="profile-select"
        value={profile}
        onChange={(event) => setProfile(event.target.value)}
        aria-label="运行档位"
      >
        <option>快速</option>
        <option>标准</option>
        <option>深度</option>
      </select>

      {!run ? (
        <button
          className="primary run-primary"
          disabled={busy || !provider}
          onClick={() => void onStart(profile)}
        >
          ▶ 启动
        </button>
      ) : (
        <>
          <span className={`status ${run.status}`}>{run.status}</span>
          <button
            disabled={busy || run.status !== "RUNNING" || !run.active_in_sidecar}
            onClick={() => void onControl("pause")}
          >
            暂停
          </button>
          <button
            disabled={busy || !["PAUSED", "RUNNING"].includes(run.status) || run.active_in_sidecar || !provider}
            onClick={() => void onControl("resume")}
          >
            继续
          </button>
          <button
            className="danger subtle"
            disabled={busy || !["RUNNING", "PAUSED"].includes(run.status)}
            onClick={() => void onControl("cancel")}
          >
            取消
          </button>
        </>
      )}
    </div>
  );
}

function DashboardView({
  run,
  dashboard,
  onRefresh,
}: {
  run: RunStatus;
  dashboard: Dashboard | null;
  onRefresh: () => void;
}) {
  if (!dashboard) return <div className="empty">正在读取 Dashboard…</div>;

  return (
    <>
      <section className="card">
        <div className="provider-title">
          <div>
            <h2>Run Dashboard</h2>
            <p className="muted mono">{run.id}</p>
          </div>
          <div className="row">
            <span className={`status ${dashboard.status}`}>{dashboard.status}</span>
            <button onClick={onRefresh}>刷新</button>
          </div>
        </div>
      </section>

      <div className="dashboard-grid">
        <div>
          <section className="card">
            <h2>阶段 / Tasks</h2>
            {Object.entries(dashboard.stages).map(([stage, tasks]) => (
              <div className="stage-item" key={stage}>
                <div className="stage-title">
                  <strong>{stage}</strong>
                  <span className="muted">{tasks.length} legs</span>
                </div>
                {tasks.map((task) => (
                  <div className="task" key={task.id}>
                    <span className="mono">{task.node}</span>
                    <span>{task.role ?? "-"}</span>
                    <span className={`status ${task.status}`}>{task.status}</span>
                    {task.error && <span className="error">{task.error}</span>}
                  </div>
                ))}
              </div>
            ))}
            {dashboard.tasks.length === 0 && <p className="muted">尚未创建 task。</p>}
          </section>
        </div>

        <div>
          <section className="card">
            <h2>Gates</h2>
            {dashboard.gates.map((gate, index) => (
              <div className="gate-item" key={`${gate.gate}-${index}`}>
                <div className="provider-title">
                  <strong>{gate.gate}</strong>
                  <span className={`status ${gate.pass ? "SUCCEEDED" : "FAILED"}`}>
                    {gate.pass ? "PASS" : "FAIL"}
                  </span>
                </div>
                {gate.issues.map((issue, i) => <p className="error" key={i}>{issue}</p>)}
              </div>
            ))}
            {dashboard.gates.length === 0 && <p className="muted">暂无门检结果。</p>}
          </section>

          <section className="card">
            <h2>最近事件</h2>
            {[...dashboard.events].reverse().slice(0, 30).map((event, index) => (
              <div className="event" key={`${event.ts}-${index}`}>
                <div className="mono">{event.type}</div>
                <div className="muted">{event.ts}</div>
              </div>
            ))}
          </section>
        </div>
      </div>
    </>
  );
}

export default App;
