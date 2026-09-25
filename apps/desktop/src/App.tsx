import React, { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  backend,
  type Dashboard,
  type ProjectView,
  type ProviderProfile,
  type RunStatus,
} from "./api";
import { ArtifactViewer, ImportPanel } from "./WorkspacePanels";

const protocolDefaults: Record<string, string> = {
  openai_chat: "https://api.openai.com/v1",
  openai_responses: "https://api.openai.com/v1",
  anthropic_messages: "https://api.anthropic.com",
  gemini: "https://generativelanguage.googleapis.com",
  openai_compatible: "http://127.0.0.1:8000/v1",
};

function App() {
  const [project, setProject] = useState<ProjectView | null>(null);
  const [providers, setProviders] = useState<ProviderProfile[]>([]);
  const [selectedProvider, setSelectedProvider] = useState("");
  const [run, setRun] = useState<RunStatus | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

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
      setRun(null);
      setDashboard(null);
      await refreshProviders(p);
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
      setNotice(kind === "pause" ? "已请求暂停" : kind === "resume" ? "已继续" : "已请求取消");
    });
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <h1>MM-Agent Desktop</h1>
          <p>MM-Final-Skill · paper-foundry 独立客户端</p>
        </div>
        <div className="badge">
          {project ? `${project.name} · ${project.profile}` : "尚未打开项目"}
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <ProjectPanel
            project={project}
            busy={busy}
            onSubmit={createOrOpen}
          />

          {project && <ImportPanel project={project} />}

          {project && (
            <ProviderPanel
              project={project}
              providers={providers}
              selectedProvider={selectedProvider}
              busy={busy}
              onSelect={setSelectedProvider}
              onRefresh={() => guarded(async () => refreshProviders(project))}
              onCreated={async () => {
                await refreshProviders(project);
                setNotice("Provider 已保存到项目配置；密钥仅保存到系统凭据库");
              }}
              onGuarded={guarded}
            />
          )}

          {project && (
            <RunPanel
              provider={selected}
              run={run}
              busy={busy}
              onStart={startRun}
              onControl={control}
            />
          )}

          {notice && <p className="success">{notice}</p>}
          {error && <p className="error">{error}</p>}
        </aside>

        <main className="main">
          {!project ? (
            <div className="empty">创建或打开一个 MM-Agent 工作区后开始。</div>
          ) : (
            <>
              {!run ? (
                <div className="empty">
                  已打开 <span className="mono">{project.root_path}</span>。导入题目、配置 Provider 后启动一炉。
                </div>
              ) : (
                <DashboardView run={run} dashboard={dashboard} onRefresh={() => void refreshRun()} />
              )}
              <ArtifactViewer project={project} />
            </>
          )}
        </main>
      </div>
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

  return (
    <section className="card">
      <h2>项目</h2>
      {project && (
        <p className="muted mono">{project.root_path}</p>
      )}
      <div className="field">
        <label>工作区路径</label>
        <input value={root} onChange={(e) => setRoot(e.target.value)} placeholder="D:\\MMProjects\\2026-C" />
      </div>
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
  const [name, setName] = useState("Primary");
  const [protocol, setProtocol] = useState("openai_responses");
  const [baseUrl, setBaseUrl] = useState(protocolDefaults.openai_responses);
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [reasoning, setReasoning] = useState("high");
  const [testResult, setTestResult] = useState("");

  function changeProtocol(value: string) {
    setProtocol(value);
    setBaseUrl(protocolDefaults[value] ?? "");
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
      });
      setApiKey("");
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
    <section className="card">
      <div className="provider-title">
        <h2>Provider</h2>
        <button onClick={onRefresh} disabled={busy}>刷新</button>
      </div>

      {providers.length > 0 && (
        <>
          <div className="field">
            <label>当前模型配置</label>
            <select value={selectedProvider} onChange={(e) => onSelect(e.target.value)}>
              {providers.map((item) => (
                <option key={item.model_profile_id} value={item.model_profile_id}>
                  {item.name} · {item.model}
                </option>
              ))}
            </select>
          </div>
          <div className="row">
            <button onClick={() => void testSelected()} disabled={!selectedProvider || busy}>Test Connection</button>
            {testResult && <span className="muted">{testResult}</span>}
          </div>
        </>
      )}

      <form onSubmit={(e) => void submit(e)}>
        <h3 style={{ marginTop: 16 }}>新增配置</h3>
        <div className="field">
          <label>名称</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </div>
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
          <label>Base URL</label>
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </div>
        <div className="field">
          <label>Model</label>
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="模型 ID" />
        </div>
        <div className="field">
          <label>API Key（不会写入 SQLite）</label>
          <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
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
        <button className="primary" disabled={busy || !name.trim() || !baseUrl.trim() || !model.trim()}>
          保存 Provider
        </button>
      </form>
    </section>
  );
}

function RunPanel({
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
    <section className="card">
      <h2>运行控制</h2>
      <div className="field">
        <label>档位</label>
        <select value={profile} onChange={(e) => setProfile(e.target.value)}>
          <option>快速</option>
          <option>标准</option>
          <option>深度</option>
        </select>
      </div>
      {!run ? (
        <button className="primary" disabled={busy || !provider} onClick={() => void onStart(profile)}>
          Start
        </button>
      ) : (
        <>
          <p><span className={`status ${run.status}`}>{run.status}</span></p>
          <div className="row wrap">
            <button disabled={busy || run.status !== "RUNNING"} onClick={() => void onControl("pause")}>Pause</button>
            <button disabled={busy || run.status !== "PAUSED" || !provider} onClick={() => void onControl("resume")}>Resume</button>
            <button className="danger" disabled={busy || !["RUNNING", "PAUSED"].includes(run.status)} onClick={() => void onControl("cancel")}>Cancel</button>
          </div>
          <p className="muted mono">{run.id}</p>
        </>
      )}
    </section>
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
