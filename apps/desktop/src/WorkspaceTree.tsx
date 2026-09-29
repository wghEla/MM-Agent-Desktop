import React, { useEffect, useMemo, useState } from "react";

import { backend, type ProjectView } from "./api";

type WorkspaceTreeItem = {
  path: string;
  name: string;
  kind: "directory" | "file";
  depth: number;
  size: number | null;
  preview_kind: "text" | "pdf" | "image" | "binary" | null;
};

type WorkspaceTreeResponse = {
  items: WorkspaceTreeItem[];
  truncated: boolean;
};

function parentPath(path: string) {
  const index = path.lastIndexOf("/");
  return index < 0 ? "" : path.slice(0, index);
}

function fileGlyph(kind: WorkspaceTreeItem["preview_kind"]) {
  if (kind === "pdf") return "PDF";
  if (kind === "image") return "IMG";
  if (kind === "text") return "TXT";
  return "BIN";
}

export function WorkspaceTree({
  project,
  selectedPath,
  onOpenFile,
  refreshKey = 0,
  live = false,
}: {
  project: ProjectView;
  selectedPath: string | null;
  onOpenFile: (path: string) => void;
  refreshKey?: number;
  live?: boolean;
}) {
  const [items, setItems] = useState<WorkspaceTreeItem[]>([]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setError("");
    try {
      const result = await backend<WorkspaceTreeResponse>(
        "GET",
        `/projects/${project.id}/workspace/tree`,
      );
      setItems(result.items);
      setTruncated(result.truncated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    setCollapsed(new Set());
    void refresh();
  }, [project.id, refreshKey]);

  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [project.id, live]);

  const visibleItems = useMemo(() => {
    const hiddenByCollapsed = (item: WorkspaceTreeItem) => {
      let parent = parentPath(item.path);
      while (parent) {
        if (collapsed.has(parent)) return true;
        parent = parentPath(parent);
      }
      return false;
    };
    return items.filter((item) => !hiddenByCollapsed(item));
  }, [items, collapsed]);

  function toggle(path: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  return (
    <section className="workspace-tree-section">
      <div className="workspace-tree-heading">
        <span>FILES</span>
        <button className="small-button" onClick={() => void refresh()} title="刷新工作区文件">↻</button>
      </div>

      <div className="workspace-tree" role="tree" aria-label="工作区文件">
        {visibleItems.map((item) => (
          <button
            key={item.path}
            type="button"
            role="treeitem"
            aria-expanded={item.kind === "directory" ? !collapsed.has(item.path) : undefined}
            className={`workspace-tree-row ${selectedPath === item.path ? "selected" : ""}`}
            style={{ paddingLeft: `${7 + item.depth * 13}px` }}
            title={item.path}
            onClick={() => item.kind === "directory" ? toggle(item.path) : onOpenFile(item.path)}
          >
            {item.kind === "directory" ? (
              <>
                <span className="tree-chevron" aria-hidden="true">{collapsed.has(item.path) ? "›" : "⌄"}</span>
                <span className="tree-folder" aria-hidden="true">▰</span>
              </>
            ) : (
              <>
                <span className="tree-chevron" aria-hidden="true" />
                <span className={`tree-file-kind ${item.preview_kind ?? "binary"}`}>
                  {fileGlyph(item.preview_kind)}
                </span>
              </>
            )}
            <span className="tree-name">{item.name}</span>
          </button>
        ))}

        {!items.length && !error && <div className="workspace-tree-empty">暂无文件。</div>}
      </div>

      {truncated && <div className="workspace-tree-warning">文件较多，仅显示前 2000 项。</div>}
      {error && <div className="workspace-tree-error">{error}</div>}
    </section>
  );
}
