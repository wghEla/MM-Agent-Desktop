import React from "react";

import type { Dashboard } from "./api";

type RailState = "idle" | "running" | "succeeded" | "failed" | "paused";

const PIPELINE = [
  "S0", "G0",
  "S1", "G1",
  "S2", "G2",
  "S3", "G3",
  "S4", "G4",
  "S5", "G5",
  "S6",
] as const;

function taskState(statuses: string[]): RailState {
  if (statuses.some((status) => status === "FAILED" || status === "CANCELLED")) return "failed";
  if (statuses.some((status) => status === "RUNNING")) return "running";
  if (statuses.some((status) => status === "PAUSED")) return "paused";
  if (statuses.length > 0 && statuses.every((status) => status === "SUCCEEDED")) return "succeeded";
  return "idle";
}

function stageState(dashboard: Dashboard | null, stage: string): RailState {
  if (!dashboard) return "idle";

  if (stage.startsWith("G")) {
    const matches = dashboard.gates.filter((gate) => {
      const name = String(gate.gate).toUpperCase();
      return name === stage || name.startsWith(stage + ":") || name.startsWith(stage + " ");
    });
    if (!matches.length) return "idle";
    return matches[matches.length - 1].pass ? "succeeded" : "failed";
  }

  const statuses = Object.entries(dashboard.stages)
    .filter(([key]) => key.toUpperCase() === stage || key.toUpperCase().startsWith(stage + "."))
    .flatMap(([, tasks]) => tasks.map((task) => task.status));
  return taskState(statuses);
}

function stateLabel(state: RailState) {
  switch (state) {
    case "running": return "运行中";
    case "succeeded": return "通过";
    case "failed": return "失败";
    case "paused": return "暂停";
    default: return "未开始";
  }
}

export function StageRail({ dashboard }: { dashboard: Dashboard | null }) {
  return (
    <section className="stage-rail" aria-label="流水线阶段">
      {PIPELINE.map((stage, index) => {
        const state = stageState(dashboard, stage);
        return (
          <React.Fragment key={stage}>
            <div className={`stage-stop ${state}`} title={`${stage} · ${stateLabel(state)}`}>
              <span className="stage-dot" aria-hidden="true" />
              <span className="stage-code">{stage}</span>
            </div>
            {index < PIPELINE.length - 1 && <span className="stage-connector" aria-hidden="true" />}
          </React.Fragment>
        );
      })}
    </section>
  );
}
