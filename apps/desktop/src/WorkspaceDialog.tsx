import React, { useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

export type WorkspaceDialogMode = "create" | "open";

const pickFolderDialog = (mode: WorkspaceDialogMode) =>
  openDialog({
    directory: true,
    multiple: false,
    title: mode === "create" ? "选择新工作区文件夹" : "选择已有 MM-Agent 工作区",
  });

export function WorkspaceDialog({
  mode,
  busy,
  onClose,
  onSubmit,
}: {
  mode: WorkspaceDialogMode;
  busy: boolean;
  onClose: () => void;
  onSubmit: (
    mode: WorkspaceDialogMode,
    root: string,
    name: string,
    profile: string,
  ) => Promise<boolean>;
}) {
  const [root, setRoot] = useState("");
  const [name, setName] = useState("数学建模项目");
  const [profile, setProfile] = useState("标准");
  const [pickerError, setPickerError] = useState("");

  const isCreate = mode === "create";

  async function pickFolder() {
    setPickerError("");
    try {
      const picked = await pickFolderDialog(mode);
      if (typeof picked !== "string" || !picked) return;
      setRoot(picked);
      if (isCreate) {
        const folderName = picked.split(/[\\/]/).filter(Boolean).pop() ?? "";
        if (folderName && (!name.trim() || name === "数学建模项目")) {
          setName(folderName);
        }
      }
    } catch (err) {
      setPickerError(
        `原生文件夹选择器不可用（${err instanceof Error ? err.message : String(err)}）；可在高级设置中手动填写路径。`,
      );
    }
  }

  async function submit() {
    if (!root.trim() || (isCreate && !name.trim())) return;
    const ok = await onSubmit(mode, root.trim(), name.trim(), profile);
    if (ok) onClose();
  }

  return (
    <div className="modal-backdrop workspace-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="workspace-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={isCreate ? "新建工作区" : "打开工作区"}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="workspace-dialog-header">
          <div>
            <span className="eyebrow">{isCreate ? "NEW WORKSPACE" : "OPEN WORKSPACE"}</span>
            <h2>{isCreate ? "新建数学建模工作区" : "打开已有工作区"}</h2>
            <p>
              {isCreate
                ? "选择一个文件夹作为项目根目录。运行真相仍由该目录中的 SQLite Runtime 管理。"
                : "选择已有 MM-Agent 工作区目录；打开操作不会启动或恢复历史 Run。"}
            </p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭">×</button>
        </header>

        <div className="workspace-dialog-body">
          <button className="workspace-picker-hero" disabled={busy} onClick={() => void pickFolder()}>
            <span className="workspace-picker-icon" aria-hidden="true">⌕</span>
            <span>
              <strong>{root ? "更换文件夹" : "选择文件夹"}</strong>
              <small>{root || (isCreate ? "为新项目选择一个目录" : "选择包含 MM-Agent 项目的目录")}</small>
            </span>
          </button>

          {pickerError && <div className="workspace-dialog-error">{pickerError}</div>}

          {isCreate && (
            <div className="workspace-dialog-fields">
              <div className="field">
                <label>项目名称</label>
                <input value={name} onChange={(event) => setName(event.target.value)} />
              </div>
              <div className="field">
                <label>默认质量档位</label>
                <select value={profile} onChange={(event) => setProfile(event.target.value)}>
                  <option>快速</option>
                  <option>标准</option>
                  <option>深度</option>
                </select>
              </div>
            </div>
          )}

          <details className="advanced-settings workspace-manual-path">
            <summary>高级：手动路径</summary>
            <div className="advanced-body">
              <div className="field">
                <label>工作区路径</label>
                <input
                  value={root}
                  onChange={(event) => setRoot(event.target.value)}
                  placeholder="D:\\MMProjects\\2026-C"
                />
              </div>
            </div>
          </details>
        </div>

        <footer className="workspace-dialog-actions">
          <button onClick={onClose} disabled={busy}>取消</button>
          <button
            className="primary"
            disabled={busy || !root.trim() || (isCreate && !name.trim())}
            onClick={() => void submit()}
          >
            {busy ? "处理中…" : isCreate ? "创建工作区" : "打开工作区"}
          </button>
        </footer>
      </section>
    </div>
  );
}
