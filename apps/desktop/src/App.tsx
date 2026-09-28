import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  backend,
  type Dashboard,
  type ProjectView,
  type ProviderProfile,
  type RunStatus,
} from "./api";
import { ArtifactViewer, ImportPanel } from "./WorkspacePanels";
import { ProviderSettings } from "./ProviderSettings";
import { StageRail } from "./StageRail";
import { WorkspaceDialog, type WorkspaceDialogMode } from "./WorkspaceDialog";
import { WorkspaceTree } from "./WorkspaceTree";

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
      .filter(
        (item) =>
          item
          && typeof item.root === "string"
          && typeof item.name === "string"
          && typeof item.profile === "string",
      )
      .map((item) => ({
        root: item.root,
        name: item.name,
        profile: item.profile,
        lastOpened: typeof item.lastOpened === "number" ? item.lastOpened : 0,
      }))
      .sort((a, b) => b.lastOpened - a.lastOpened)
      .slice(0, 8);
  } catch {
    return [];
  }
}

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
  const [workspaceDialog, setWorkspaceDialog] = useState<WorkspaceDialogMode | null>(null);
  const [selectedWorkspacePath, setSelectedWorkspacePath] = useState<string | null>(null);
  const [workspaceRevision, setWorkspaceRevision] = useState(0);

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

  async function guarded(action: () => Promise<void>): Promise<boolean> {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function createOrOpen(mode: "create" | "open", root: string, name: string, profile: string) {
    return guarded(async () => {
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
      setSelectedWorkspacePath(null);
      await refreshProviders(p);
      await loadRunHistory(p, mode === "open");
      setNotice(mode === "create" ? "项目已创建" : "项目已打开");
    });
  }

  function openWorkspaceDialog(mode: WorkspaceDialogMode) {
    setError("");
    setNotice("");
    setWorkspaceDialog(mode);
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
            <WorkspaceLauncher
              busy={busy}
              onCreate={() => openWorkspaceDialog("create")}
              onOpen={() => openWorkspaceDialog("open")}
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
                  setSelectedWorkspacePath(null);
                }}
              />
              <WorkspaceTree
                project={project}
                selectedPath={selectedWorkspacePath}
                onOpenFile={setSelectedWorkspacePath}
                refreshKey={workspaceRevision}
                live={run?.status === "RUNNING"}
              />
              <ImportPanel
                project={project}
                onImported={() => setWorkspaceRevision((value) => value + 1)}
              />

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
            <>
              {notice && <div className="notice-banner success">{notice}</div>}
              {error && <div className="notice-banner error">{error}</div>}
              <WelcomeSurface
                recent={recentWorkspaces}
                busy={busy}
                onCreate={() => openWorkspaceDialog("create")}
                onOpenDialog={() => openWorkspaceDialog("open")}
                onOpenRecent={(workspace) => createOrOpen("open", workspace.root, workspace.name, workspace.profile)}
                onRemoveRecent={(root) => {
                  setRecentWorkspaces((current) => {
                    const next = current.filter((item) => item.root !== root);
                    window.localStorage.setItem(RECENT_WORKSPACES_KEY, JSON.stringify(next));
                    return next;
                  });
                }}
              />
            </>
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
                  <WorkspaceReadySurface
                    project={project}
                    hasProvider={Boolean(selected)}
                    onOpenSettings={() => setSettingsOpen(true)}
                  />
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
            <ArtifactViewer project={project} requestedPath={selectedWorkspacePath} refreshKey={workspaceRevision} live={run?.status === "RUNNING"} />
          ) : (
            <div className="dock-empty">打开工作区后，这里会显示论文、图表、结果、审稿与交付物。</div>
          )}
        </aside>
      </div>

      {workspaceDialog && (
        <WorkspaceDialog
          mode={workspaceDialog}
          busy={busy}
          onClose={() => setWorkspaceDialog(null)}
          onSubmit={createOrOpen}
          error={error}
        />
      )}

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
              <ProviderSettings
                project={project}
                providers={providers}
                selectedProvider={selectedProvider}
                busy={busy}
                onSelect={setSelectedProvider}
                onChanged={async () => {
                  await refreshProviders(project);
                  setNotice("Provider 设置已更新");
                }}
                onGuarded={guarded}
                externalError={error}
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

function WorkspaceReadySurface({
  project,
  hasProvider,
  onOpenSettings,
}: {
  project: ProjectView;
  hasProvider: boolean;
  onOpenSettings: () => void;
}) {
  return (
    <div className="workbench-empty workspace-ready-surface">
      <div className="empty-kicker">WORKSPACE READY</div>
      <h2>工作区已经就绪，完成模型与材料配置后即可启动。</h2>
      <p>
        <span className="mono">{project.root_path}</span>
      </p>

      <div className="setup-checklist">
        <div className="setup-check done">
          <span className="setup-check-mark">✓</span>
          <div>
            <strong>1 · 工作区</strong>
            <small>项目目录与 SQLite Runtime 已建立</small>
          </div>
        </div>

        <button
          className={`setup-check ${hasProvider ? "done" : "actionable"}`}
          onClick={onOpenSettings}
        >
          <span className="setup-check-mark">{hasProvider ? "✓" : "2"}</span>
          <div>
            <strong>2 · 模型</strong>
            <small>{hasProvider ? "Provider 已配置，可在设置中切换" : "配置 Provider、Model 与凭据"}</small>
          </div>
          {!hasProvider && <span className="setup-check-action">配置 →</span>}
        </button>

        <div className="setup-check">
          <span className="setup-check-mark">3</span>
          <div>
            <strong>3 · 材料</strong>
            <small>从左侧导入题目和数据；文件树会立即刷新</small>
          </div>
        </div>
      </div>

      <p className="workspace-ready-hint">
        启动按钮位于顶部工具栏。Runtime 会继续通过 Gate 检查缺失材料，不会因为 UI 显示“就绪”而跳过验证。
      </p>
    </div>
  );
}

function WorkspaceLauncher({
  busy,
  onCreate,
  onOpen,
}: {
  busy: boolean;
  onCreate: () => void;
  onOpen: () => void;
}) {
  return (
    <section className="workspace-launcher">
      <button className="primary workspace-launch-button" disabled={busy} onClick={onCreate}>
        <span aria-hidden="true">＋</span>
        新建工作区
      </button>
      <button className="workspace-launch-button" disabled={busy} onClick={onOpen}>
        <span aria-hidden="true">⌕</span>
        打开工作区
      </button>
      <p>工作区是项目根目录；运行状态与产物仍由 Runtime / SQLite 管理。</p>
    </section>
  );
}

function WelcomeSurface({
  recent,
  busy,
  onCreate,
  onOpenDialog,
  onOpenRecent,
  onRemoveRecent,
}: {
  recent: RecentWorkspace[];
  busy: boolean;
  onCreate: () => void;
  onOpenDialog: () => void;
  onOpenRecent: (workspace: RecentWorkspace) => Promise<boolean>;
  onRemoveRecent: (root: string) => void;
}) {
  return (
    <div className="welcome-surface onboarding-surface">
      <div className="welcome-mark" aria-hidden="true">M</div>
      <span className="eyebrow">MM-AGENT DESKTOP</span>
      <h2>从工作区开始，把建模全过程固定在一个可追踪的桌面工作台里。</h2>
      <p>第一次使用只需要三步。项目运行以后，中间展示 S0–S6 / Gate，右侧持续展示论文、图表和证据载体。</p>

      <div className="onboarding-steps" aria-label="首次使用步骤">
        <div className="onboarding-step active">
          <span>1</span>
          <div><strong>工作区</strong><small>新建或打开项目目录</small></div>
        </div>
        <div className="onboarding-step">
          <span>2</span>
          <div><strong>模型</strong><small>配置 Provider 与凭据</small></div>
        </div>
        <div className="onboarding-step">
          <span>3</span>
          <div><strong>材料</strong><small>导入题目与数据后启动</small></div>
        </div>
      </div>

      <div className="welcome-actions">
        <button className="primary" disabled={busy} onClick={onCreate}>＋ 新建工作区</button>
        <button disabled={busy} onClick={onOpenDialog}>打开已有工作区</button>
      </div>

      {recent.length > 0 && (
        <div className="recent-workspaces">
          <div className="recent-heading">最近工作区</div>
          {recent.map((workspace) => (
            <div className="recent-workspace-row" key={workspace.root}>
              <button
                disabled={busy}
                className="recent-workspace"
                onClick={() => void onOpenRecent(workspace)}
              >
                <span className="recent-workspace-icon">Σ</span>
                <span className="recent-workspace-copy">
                  <strong>{workspace.name}</strong>
                  <span className="mono">{workspace.root}</span>
                </span>
                <span className="recent-workspace-profile">{workspace.profile}</span>
              </button>
              <button
                className="recent-remove"
                disabled={busy}
                onClick={() => onRemoveRecent(workspace.root)}
                title="从最近列表移除（不会删除工作区）"
                aria-label={`从最近列表移除 ${workspace.name}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="welcome-points">
        <span>SQLite durable state</span>
        <span>Fail-closed gates</span>
        <span>Frozen Truth</span>
      </div>
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
