import { invoke } from "@tauri-apps/api/core";

export type BackendResponse<T> = {
  status: number;
  body: T | { detail?: string } | string;
};

export async function backend<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await invoke<BackendResponse<T>>("backend_request", {
    method,
    path,
    body: body ?? null,
  });
  if (response.status < 200 || response.status >= 300) {
    const payload = response.body;
    const detail =
      typeof payload === "string"
        ? payload
        : typeof payload === "object" && payload && "detail" in payload
          ? String((payload as { detail?: unknown }).detail ?? "请求失败")
          : "请求失败";
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.body as T;
}

export type ProjectView = {
  id: string;
  name: string;
  root_path: string;
  profile: string;
  created_at: string;
};

export type ProviderCapabilities = {
  protocol: string;
  tool_calling: boolean;
  image_input: boolean;
  streaming: boolean;
  reasoning_levels: string[];
  max_output_tokens_limit: number | null;
};

export type ProviderProfile = {
  provider_id: string;
  model_profile_id: string;
  name: string;
  protocol: string;
  base_url: string;
  has_api_key: boolean;
  auth_kind: "api_key" | "oauth" | "none";
  model: string;
  reasoning: string | null;
  max_output_tokens: number | null;
  timeout_s: number | null;
  extra: Record<string, unknown>;
  capabilities: ProviderCapabilities;
};

export type ProviderPreset = {
  id: string;
  label: string;
  protocol: string;
  base_url: string;
  auth_methods: Array<"api_key" | "oauth" | "none">;
  discover_models: boolean;
  base_url_editable: boolean;
  oauth: {
    flow: "authorization_code_pkce" | "device_code";
    authorize_path: string;
    token_path: string;
  } | null;
  note: string;
  capabilities: ProviderCapabilities;
};

export type ModelDiscoveryResult = {
  ok: boolean;
  models: string[];
  detail: string;
  endpoint: string;
};

export type RunStatus = {
  id: string;
  status: string;
  profile: string;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  active_in_sidecar: boolean;
  last_error: string | null;
};

export type Dashboard = {
  run_id: string;
  status: string;
  profile: string;
  profile_config: Record<string, unknown> | null;
  stages: Record<string, Array<{
    id: string;
    node: string;
    role: string | null;
    status: string;
    attempt: number;
    error: string | null;
  }>>;
  tasks: Array<{
    id: string;
    node: string;
    role: string | null;
    status: string;
    attempt: number;
    error: string | null;
  }>;
  events: Array<{
    ts: string;
    type: string;
    task: string | null;
    payload: Record<string, unknown>;
  }>;
  gates: Array<{
    gate: string;
    pass: boolean;
    issues: string[];
  }>;
};
