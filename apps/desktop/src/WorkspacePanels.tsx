import React, { useEffect, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

import { backend, type ProjectView } from "./api";

type ArtifactItem = {
  path: string;
  name: string;
  size: number;
  kind: "text" | "pdf" | "image" | "binary";
  mime_type: string | null;
};

type ArtifactPreview = {
  path: string;
  kind: "text" | "pdf" | "image" | "binary";
  mime_type: string;
  size: number;
  text?: string;
  base64?: string;
};

export function ImportPanel({ project }: { project: ProjectView }) {
  const [kind, setKind] = useState("problem");
  const [sources, setSources] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [pickerError, setPickerError] = useState("");

  async function pickFiles() {
    setPickerError("");
    try {
      const picked = await openDialog({
        multiple: true,
        title: "选择要导入的题目 / 附件文件",
      });
      const paths = Array.isArray(picked) ? picked : typeof picked === "string" ? [picked] : [];
      if (paths.length) {
        setSources((current) => {
          const lines = current.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
          const merged = [...lines, ...paths.filter((p) => !lines.includes(p))];
          return merged.join("\n");
        });
      }
    } catch (err) {
      setPickerError(
        `原生文件选择器不可用（${err instanceof Error ? err.message : String(err)}）；可手动填写路径。`,
      );
    }
  }

  async function submit() {
    const paths = sources
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!paths.length) return;
    setBusy(true);
    setResult("");
    try {
      const response = await backend<{ imported: Array<{ path: string }> }>(
        "POST",
        `/projects/${project.id}/imports`,
        { sources: paths, kind },
      );
      setResult(`已导入 ${response.imported.length} 个文件：${response.imported.map((x) => x.path).join("，")}`);
      setSources("");
    } catch (err) {
      setResult(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>导入题目 / 附件</h2>
      <div className="field">
        <label>类型</label>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="problem">题目</option>
          <option value="data">数据附件</option>
        </select>
      </div>
      <div className="field">
        <label>源文件路径（每行一个）</label>
        <textarea
          value={sources}
          onChange={(e) => setSources(e.target.value)}
          placeholder={"D:\\Downloads\\题目.pdf\nD:\\Downloads\\附件.xlsx"}
          rows={4}
        />
      </div>
      <button disabled={busy} onClick={() => void pickFiles()}>
        浏览选择文件…
      </button>
      {pickerError && <p className="error">{pickerError}</p>}
      <button className="primary" disabled={busy || !sources.trim()} onClick={() => void submit()}>
        {busy ? "导入中…" : "导入"}
      </button>
      {result && <p className="muted">{result}</p>}
    </section>
  );
}

export function ArtifactViewer({ project }: { project: ProjectView }) {
  const [items, setItems] = useState<ArtifactItem[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [preview, setPreview] = useState<ArtifactPreview | null>(null);
  const [error, setError] = useState("");

  async function refresh() {
    setError("");
    try {
      const list = await backend<ArtifactItem[]>("GET", `/projects/${project.id}/artifacts`);
      setItems(list);
      if (selected && !list.some((item) => item.path === selected)) {
        setSelected("");
        setPreview(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function open(path: string) {
    setSelected(path);
    setPreview(null);
    setError("");
    try {
      const value = await backend<ArtifactPreview>(
        "POST",
        `/projects/${project.id}/artifacts/read`,
        { path },
      );
      setPreview(value);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void refresh();
  }, [project.id]);

  return (
    <section className="card artifact-card">
      <div className="provider-title">
        <div>
          <h2>Artifacts</h2>
          <p className="muted">交付、论文、审稿、交接、求解与日志</p>
        </div>
        <button onClick={() => void refresh()}>刷新</button>
      </div>

      <div className="artifact-layout">
        <div className="artifact-list">
          {items.map((item) => (
            <button
              className={`artifact-row ${selected === item.path ? "selected" : ""}`}
              key={item.path}
              onClick={() => void open(item.path)}
            >
              <span className="artifact-kind">{item.kind}</span>
              <span className="artifact-path">{item.path}</span>
              <span className="artifact-size">{formatBytes(item.size)}</span>
            </button>
          ))}
          {!items.length && <p className="muted">暂时没有可浏览产物。</p>}
        </div>

        <div className="artifact-preview">
          {!preview && <div className="empty">选择左侧产物进行预览。</div>}
          {preview?.kind === "text" && (
            <pre className="text-preview">{preview.text}</pre>
          )}
          {preview?.kind === "image" && preview.base64 && (
            <img
              className="image-preview"
              src={`data:${preview.mime_type};base64,${preview.base64}`}
              alt={preview.path}
            />
          )}
          {preview?.kind === "pdf" && preview.base64 && (
            <iframe
              className="pdf-preview"
              title={preview.path}
              src={`data:application/pdf;base64,${preview.base64}`}
            />
          )}
          {preview?.kind === "binary" && (
            <div className="empty">该文件不提供内嵌预览。大小 {formatBytes(preview.size)}。</div>
          )}
        </div>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
