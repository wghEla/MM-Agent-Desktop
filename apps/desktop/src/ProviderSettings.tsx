import React, { FormEvent, useEffect, useMemo, useState } from "react";

import {
  backend,
  type ModelDiscoveryResult,
  type ProjectView,
  type ProviderCapabilities,
  type ProviderPreset,
  type ProviderProfile,
} from "./api";

type ProviderFormState = {
  name: string;
  protocol: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  authMode: "api_key" | "none";
  reasoning: string;
  maxOutputTokens: string;
  timeoutS: string;
  imageInput: boolean;
  reasoningEffort: boolean;
  authStyle: "bearer" | "x-api-key" | "none";
  completionsPath: string;
  baseExtra: Record<string, unknown>;
};

const protocolDefaults: Record<string, string> = {
  openai_chat: "https://api.openai.com/v1",
  openai_responses: "https://api.openai.com/v1",
  anthropic_messages: "https://api.anthropic.com",
  gemini: "https://generativelanguage.googleapis.com",
  openai_compatible: "",
};

function blankForm(): ProviderFormState {
  return {
    name: "Primary",
    protocol: "openai_responses",
    baseUrl: protocolDefaults.openai_responses,
    model: "",
    apiKey: "",
    authMode: "api_key",
    reasoning: "",
    maxOutputTokens: "",
    timeoutS: "300",
    imageInput: false,
    reasoningEffort: false,
    authStyle: "bearer",
    completionsPath: "/chat/completions",
    baseExtra: {},
  };
}

function formFromProfile(profile: ProviderProfile): ProviderFormState {
  const authStyle =
    profile.extra.auth_style === "x-api-key"
      ? "x-api-key"
      : profile.extra.auth_style === "none"
        ? "none"
        : "bearer";
  return {
    name: profile.name,
    protocol: profile.protocol,
    baseUrl: profile.base_url,
    model: profile.model,
    apiKey: "",
    authMode: profile.has_api_key ? "api_key" : "none",
    reasoning: profile.reasoning ?? "",
    maxOutputTokens: profile.max_output_tokens ? String(profile.max_output_tokens) : "",
    timeoutS: profile.timeout_s ? String(profile.timeout_s) : "300",
    imageInput: Boolean(profile.extra.image_input),
    reasoningEffort: Boolean(profile.extra.reasoning_effort),
    authStyle,
    completionsPath:
      typeof profile.extra.completions_path === "string"
        ? profile.extra.completions_path
        : "/chat/completions",
    baseExtra: { ...profile.extra },
  };
}

function providerExtra(form: ProviderFormState) {
  if (form.protocol !== "openai_compatible") {
    return { ...form.baseExtra };
  }
  return {
    ...form.baseExtra,
    image_input: form.imageInput,
    reasoning_effort: form.reasoningEffort,
    auth_style: form.authStyle,
    completions_path: form.completionsPath || "/chat/completions",
  };
}

function numberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
}

function capabilityPills(capabilities: ProviderCapabilities) {
  return [
    capabilities.tool_calling ? "Tools" : null,
    capabilities.image_input ? "Vision" : null,
    capabilities.reasoning_levels.length ? "Reasoning" : null,
    capabilities.streaming ? "Streaming" : null,
  ].filter((item): item is string => Boolean(item));
}

export function ProviderSettings({
  project,
  providers,
  selectedProvider,
  busy,
  onSelect,
  onChanged,
  onGuarded,
}: {
  project: ProjectView;
  providers: ProviderProfile[];
  selectedProvider: string;
  busy: boolean;
  onSelect: (value: string) => void;
  onChanged: () => Promise<void>;
  onGuarded: (action: () => Promise<void>) => Promise<boolean>;
}) {
  const selected = providers.find((item) => item.model_profile_id === selectedProvider) ?? null;
  const [catalog, setCatalog] = useState<ProviderPreset[]>([]);
  const [catalogError, setCatalogError] = useState("");
  const [showCreate, setShowCreate] = useState(providers.length === 0);
  const [editing, setEditing] = useState(false);
  const [presetId, setPresetId] = useState("");
  const [form, setForm] = useState<ProviderFormState>(blankForm);
  const [testResult, setTestResult] = useState("");
  const [localError, setLocalError] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [modelDetail, setModelDetail] = useState("");
  const [discoverBusy, setDiscoverBusy] = useState(false);
  const [credentialMode, setCredentialMode] = useState(false);
  const [replacementKey, setReplacementKey] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  useEffect(() => {
    let active = true;
    void backend<ProviderPreset[]>("GET", "/providers/catalog")
      .then((value) => {
        if (!active) return;
        setCatalog(value);
        setCatalogError("");
        if (value.length) {
          setPresetId(value[0].id);
          setForm((current) =>
            providers.length
              ? current
              : {
                  ...blankForm(),
                  name: value[0].label,
                  protocol: value[0].protocol,
                  baseUrl: value[0].base_url,
                  authMode: value[0].auth_methods.includes("none") ? "none" : "api_key",
                },
          );
        }
      })
      .catch((err) => {
        if (active) setCatalogError(err instanceof Error ? err.message : String(err));
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selected) return;
    if (!editing) {
      setModels([]);
      setModelDetail("");
      setCredentialMode(false);
      setReplacementKey("");
      setDeleteConfirm(false);
    }
  }, [selected?.model_profile_id]);

  const selectedPreset = useMemo(
    () => catalog.find((item) => item.id === presetId) ?? null,
    [catalog, presetId],
  );

  const formCapabilities = useMemo<ProviderCapabilities>(() => {
    if (form.protocol === "openai_compatible") {
      return {
        protocol: form.protocol,
        tool_calling: true,
        image_input: form.imageInput,
        streaming: false,
        reasoning_levels: form.reasoningEffort ? ["low", "medium", "high"] : [],
        max_output_tokens_limit: null,
      };
    }
    const matching = catalog.find((item) => item.protocol === form.protocol);
    return matching?.capabilities ?? {
      protocol: form.protocol,
      tool_calling: true,
      image_input: false,
      streaming: false,
      reasoning_levels: [],
      max_output_tokens_limit: null,
    };
  }, [catalog, form.protocol, form.imageInput, form.reasoningEffort]);

  const requiresApiKey = Boolean(
    selectedPreset
      && selectedPreset.auth_methods.includes("api_key")
      && !selectedPreset.auth_methods.includes("none"),
  );

  function applyPreset(preset: ProviderPreset) {
    setPresetId(preset.id);
    setForm({
      ...blankForm(),
      name: preset.label,
      protocol: preset.protocol,
      baseUrl: preset.base_url,
      authMode: preset.auth_methods.includes("none") ? "none" : "api_key",
    });
    setModels([]);
    setModelDetail("");
    setLocalError("");
  }

  function changeProtocol(protocol: string) {
    setPresetId("");
    setForm((current) => ({
      ...current,
      protocol,
      baseUrl: protocolDefaults[protocol] ?? "",
      reasoning: "",
      imageInput: false,
      reasoningEffort: false,
      authStyle: "bearer",
      completionsPath: "/chat/completions",
      baseExtra: {},
    }));
    setModels([]);
    setModelDetail("");
  }

  async function discoverForCreate() {
    if (!form.baseUrl.trim()) return;
    setDiscoverBusy(true);
    setLocalError("");
    setModelDetail("");
    try {
      const result = await backend<ModelDiscoveryResult>(
        "POST",
        "/providers/discover-models",
        {
          protocol: form.protocol,
          base_url: form.baseUrl,
          api_key: form.authMode === "api_key" ? form.apiKey || null : null,
          extra: providerExtra(form),
        },
      );
      setModels(result.models);
      setModelDetail((result.ok ? "✓ " : "· ") + result.detail);
      if (!form.model && result.models.length) {
        setForm((current) => ({ ...current, model: result.models[0] }));
      }
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setDiscoverBusy(false);
    }
  }

  async function discoverSaved() {
    if (!selected) return;
    setDiscoverBusy(true);
    setLocalError("");
    setModelDetail("");
    try {
      const result = await backend<ModelDiscoveryResult>(
        "GET",
        "/projects/" + project.id + "/providers/" + selected.model_profile_id + "/models",
      );
      setModels(result.models);
      setModelDetail((result.ok ? "✓ " : "· ") + result.detail);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : String(err));
    } finally {
      setDiscoverBusy(false);
    }
  }

  async function createProvider(event: FormEvent) {
    event.preventDefault();
    const ok = await onGuarded(async () => {
      await backend("POST", "/projects/" + project.id + "/providers", {
        name: form.name,
        protocol: form.protocol,
        base_url: form.baseUrl,
        model: form.model,
        api_key: form.authMode === "api_key" ? form.apiKey || null : null,
        reasoning: form.reasoning || null,
        max_output_tokens: numberOrNull(form.maxOutputTokens),
        timeout_s: numberOrNull(form.timeoutS) ?? 300,
        extra: providerExtra(form),
      });
      await onChanged();
    });
    if (ok) {
      setForm(blankForm());
      setShowCreate(false);
      setEditing(false);
      setModels([]);
      setModelDetail("");
    }
  }

  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const ok = await onGuarded(async () => {
      await backend(
        "POST",
        "/projects/" + project.id + "/providers/" + selected.model_profile_id,
        {
          name: form.name,
          protocol: form.protocol,
          base_url: form.baseUrl,
          model: form.model,
          reasoning: form.reasoning || null,
          max_output_tokens: numberOrNull(form.maxOutputTokens),
          timeout_s: numberOrNull(form.timeoutS) ?? 300,
          extra: providerExtra(form),
        },
      );
      await onChanged();
    });
    if (ok) {
      setEditing(false);
      setModels([]);
      setModelDetail("");
    }
  }

  async function replaceCredential() {
    if (!selected || !replacementKey) return;
    const ok = await onGuarded(async () => {
      await backend(
        "POST",
        "/projects/" + project.id + "/providers/" + selected.model_profile_id + "/credential",
        { api_key: replacementKey },
      );
      await onChanged();
    });
    if (ok) {
      setReplacementKey("");
      setCredentialMode(false);
    }
  }

  async function clearCredential() {
    if (!selected) return;
    const ok = await onGuarded(async () => {
      await backend(
        "POST",
        "/projects/" + project.id + "/providers/" + selected.model_profile_id + "/credential/clear",
      );
      await onChanged();
    });
    if (ok) {
      setCredentialMode(false);
      setReplacementKey("");
    }
  }

  async function deleteSelected() {
    if (!selected) return;
    if (!deleteConfirm) {
      setDeleteConfirm(true);
      return;
    }
    const ok = await onGuarded(async () => {
      await backend(
        "POST",
        "/projects/" + project.id + "/providers/" + selected.model_profile_id + "/delete",
      );
      await onChanged();
    });
    if (ok) {
      setDeleteConfirm(false);
      setShowCreate(false);
      setEditing(false);
    }
  }

  async function testSelected() {
    if (!selected) return;
    setTestResult("测试中…");
    setLocalError("");
    try {
      const result = await backend<{ ok: boolean; detail: string }>(
        "POST",
        "/projects/" + project.id + "/providers/" + selected.model_profile_id + "/test",
      );
      setTestResult((result.ok ? "✓ " : "✗ ") + result.detail);
    } catch (err) {
      setTestResult("");
      setLocalError(err instanceof Error ? err.message : String(err));
    }
  }

  function startCreate() {
    setShowCreate(true);
    setEditing(false);
    setLocalError("");
    setTestResult("");
    setModels([]);
    setModelDetail("");
    if (catalog.length) applyPreset(catalog[0]);
    else setForm(blankForm());
  }

  function startEdit() {
    if (!selected) return;
    setForm(formFromProfile(selected));
    setPresetId("");
    setShowCreate(false);
    setEditing(true);
    setLocalError("");
    setModels([]);
    setModelDetail("");
  }

  function renderModelField(allowDiscovery: boolean) {
    return (
      <div className="field">
        <label>Model ID</label>
        <div className="model-field-row">
          <input
            list="mmagent-provider-models"
            value={form.model}
            onChange={(event) => setForm((current) => ({ ...current, model: event.target.value }))}
            placeholder="精确模型 ID；列表不可用时可手动输入"
          />
          {allowDiscovery && (
            <button
              type="button"
              disabled={discoverBusy || !form.baseUrl.trim()}
              onClick={() => void discoverForCreate()}
            >
              {discoverBusy ? "发现中…" : "发现模型"}
            </button>
          )}
        </div>
        <datalist id="mmagent-provider-models">
          {models.map((item) => <option key={item} value={item} />)}
        </datalist>
        {modelDetail && <span className="field-hint">{modelDetail}</span>}
      </div>
    );
  }

  function renderAdvanced() {
    return (
      <details className="advanced-settings">
        <summary>Advanced</summary>
        <div className="advanced-body">
          <div className="settings-section two-column-fields">
            <div className="field">
              <label>协议</label>
              <select value={form.protocol} onChange={(event) => changeProtocol(event.target.value)}>
                <option value="openai_responses">OpenAI Responses</option>
                <option value="openai_chat">OpenAI Chat</option>
                <option value="anthropic_messages">Anthropic Messages</option>
                <option value="gemini">Gemini</option>
                <option value="openai_compatible">OpenAI Compatible</option>
              </select>
            </div>
            <div className="field">
              <label>Timeout (s)</label>
              <input
                inputMode="numeric"
                value={form.timeoutS}
                onChange={(event) => setForm((current) => ({ ...current, timeoutS: event.target.value }))}
              />
            </div>
          </div>

          <div className="field">
            <label>Base URL</label>
            <input
              value={form.baseUrl}
              onChange={(event) => {
                setForm((current) => ({ ...current, baseUrl: event.target.value }));
                setModels([]);
                setModelDetail("");
              }}
              placeholder="https://…/v1"
            />
          </div>

          <div className="settings-section two-column-fields">
            {formCapabilities.reasoning_levels.length > 0 ? (
              <div className="field">
                <label>Reasoning</label>
                <select
                  value={form.reasoning}
                  onChange={(event) => setForm((current) => ({ ...current, reasoning: event.target.value }))}
                >
                  <option value="">Provider 默认</option>
                  {formCapabilities.reasoning_levels.map((level) => (
                    <option key={level} value={level}>{level}</option>
                  ))}
                </select>
              </div>
            ) : (
              <div className="field">
                <label>Reasoning</label>
                <div className="read-only-field">该协议当前未声明 reasoning 档位</div>
              </div>
            )}
            <div className="field">
              <label>Max output tokens</label>
              <input
                inputMode="numeric"
                value={form.maxOutputTokens}
                onChange={(event) => setForm((current) => ({ ...current, maxOutputTokens: event.target.value }))}
                placeholder="Provider / Runtime 默认"
              />
            </div>
          </div>

          {form.protocol === "openai_compatible" && (
            <>
              <div className="capability-options">
                <label>
                  <input
                    type="checkbox"
                    checked={form.imageInput}
                    onChange={(event) => setForm((current) => ({ ...current, imageInput: event.target.checked }))}
                  />
                  渠道支持图片输入
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={form.reasoningEffort}
                    onChange={(event) => setForm((current) => ({
                      ...current,
                      reasoningEffort: event.target.checked,
                      reasoning: event.target.checked ? current.reasoning : "",
                    }))}
                  />
                  渠道支持 reasoning_effort
                </label>
              </div>
              <div className="settings-section two-column-fields">
                <div className="field">
                  <label>Auth style</label>
                  <select
                    value={form.authStyle}
                    onChange={(event) => setForm((current) => ({
                      ...current,
                      authStyle: event.target.value as ProviderFormState["authStyle"],
                    }))}
                  >
                    <option value="bearer">Bearer</option>
                    <option value="x-api-key">x-api-key</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <div className="field">
                  <label>Completions path</label>
                  <input
                    value={form.completionsPath}
                    onChange={(event) => setForm((current) => ({
                      ...current,
                      completionsPath: event.target.value,
                    }))}
                  />
                </div>
              </div>
            </>
          )}
        </div>
      </details>
    );
  }

  return (
    <div className="provider-settings-grid">
      <aside className="provider-settings-list">
        <div className="provider-list-heading">
          <span>Providers</span>
          <button className="small-button" onClick={startCreate}>＋</button>
        </div>

        {providers.map((item) => (
          <button
            key={item.model_profile_id}
            className={"provider-nav-item " + (selectedProvider === item.model_profile_id && !showCreate ? "selected" : "")}
            onClick={() => {
              onSelect(item.model_profile_id);
              setShowCreate(false);
              setEditing(false);
              setTestResult("");
              setLocalError("");
            }}
          >
            <span className="provider-avatar">{item.name.slice(0, 1).toUpperCase()}</span>
            <span className="provider-nav-copy">
              <strong>{item.name}</strong>
              <span>{item.model}</span>
            </span>
            <span
              className={"credential-dot " + (item.has_api_key ? "" : "keyless")}
              title={item.has_api_key ? "API Key 已保存" : "Keyless"}
            />
          </button>
        ))}

        <button
          className={"provider-nav-item add-provider " + (showCreate ? "selected" : "")}
          onClick={startCreate}
        >
          <span className="provider-avatar">＋</span>
          <span className="provider-nav-copy">
            <strong>添加 Provider</strong>
            <span>Catalog / API Key / Compatible</span>
          </span>
        </button>
      </aside>

      <section className="provider-settings-detail">
        {catalogError && <div className="settings-inline-error">{catalogError}</div>}
        {localError && <div className="settings-inline-error">{localError}</div>}

        {showCreate || !selected ? (
          <form onSubmit={(event) => void createProvider(event)}>
            <div className="detail-heading">
              <div>
                <span className="eyebrow">NEW PROVIDER</span>
                <h3>添加模型渠道</h3>
                <p>选择渠道后应用协议与 Endpoint；模型列表可自动发现，始终保留手动 Model ID fallback。</p>
              </div>
            </div>

            <div className="preset-grid">
              {catalog.map((preset) => (
                <button
                  type="button"
                  key={preset.id}
                  className={"preset-button " + (presetId === preset.id ? "selected" : "")}
                  onClick={() => applyPreset(preset)}
                  title={preset.note}
                >
                  <span className="preset-mark">{preset.label.slice(0, 1)}</span>
                  <span>{preset.label}</span>
                </button>
              ))}
            </div>

            <div className="settings-section">
              <h4>Authentication</h4>
              {selectedPreset?.auth_methods.includes("none") && (
                <div className="auth-mode-tabs">
                  <button
                    type="button"
                    className={form.authMode === "api_key" ? "selected" : ""}
                    onClick={() => setForm((current) => ({ ...current, authMode: "api_key" }))}
                  >
                    API Key
                  </button>
                  <button
                    type="button"
                    className={form.authMode === "none" ? "selected" : ""}
                    onClick={() => setForm((current) => ({ ...current, authMode: "none", apiKey: "" }))}
                  >
                    No auth
                  </button>
                </div>
              )}

              {form.authMode === "api_key" && (
                <div className="field">
                  <label>API Key</label>
                  <input
                    type="password"
                    autoComplete="off"
                    value={form.apiKey}
                    onChange={(event) => setForm((current) => ({ ...current, apiKey: event.target.value }))}
                    placeholder="仅写入 Windows Credential Manager"
                  />
                  <span className="field-hint">保存后不会在 UI、SQLite、文档或日志中回显真实密钥。</span>
                </div>
              )}
            </div>

            <div className="settings-section two-column-fields">
              <div className="field">
                <label>名称</label>
                <input
                  value={form.name}
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                />
              </div>
              {selectedPreset?.base_url_editable && (
                <div className="field">
                  <label>Base URL</label>
                  <input
                    value={form.baseUrl}
                    onChange={(event) => setForm((current) => ({ ...current, baseUrl: event.target.value }))}
                    placeholder="渠道提供的 API 根地址"
                  />
                </div>
              )}
            </div>

            {renderModelField(Boolean(selectedPreset?.discover_models ?? true))}

            <div className="capability-summary">
              {capabilityPills(formCapabilities).map((pill) => <span key={pill}>{pill}</span>)}
            </div>

            {renderAdvanced()}

            <div className="settings-actions">
              <button
                className="primary"
                disabled={
                  busy
                  || !form.name.trim()
                  || !form.baseUrl.trim()
                  || !form.model.trim()
                  || (requiresApiKey && form.authMode === "api_key" && !form.apiKey.trim())
                }
              >
                保存 Provider
              </button>
            </div>
          </form>
        ) : editing ? (
          <form onSubmit={(event) => void saveEdit(event)}>
            <div className="detail-heading">
              <div>
                <span className="eyebrow">EDIT PROVIDER</span>
                <h3>{selected.name}</h3>
                <p>修改 Endpoint / Model 不会读取或回显已保存的 API Key。</p>
              </div>
              <button type="button" onClick={() => setEditing(false)}>取消编辑</button>
            </div>

            <div className="settings-section two-column-fields">
              <div className="field">
                <label>名称</label>
                <input
                  value={form.name}
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                />
              </div>
              {renderModelField(false)}
            </div>

            {models.length > 0 && (
              <div className="field">
                <label>已发现模型</label>
                <select
                  value={models.includes(form.model) ? form.model : ""}
                  onChange={(event) => {
                    if (event.target.value) {
                      setForm((current) => ({ ...current, model: event.target.value }));
                    }
                  }}
                >
                  <option value="">选择模型…</option>
                  {models.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </div>
            )}

            {renderAdvanced()}

            <div className="settings-actions">
              <button
                className="primary"
                disabled={busy || !form.name.trim() || !form.baseUrl.trim() || !form.model.trim()}
              >
                保存修改
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
              <div className="provider-heading-actions">
                <button onClick={() => void discoverSaved()} disabled={busy || discoverBusy}>
                  {discoverBusy ? "发现中…" : "刷新模型列表"}
                </button>
                <button onClick={startEdit} disabled={busy}>编辑</button>
              </div>
            </div>

            <div className="provider-status-card">
              <div>
                <span className="status-kicker">Authentication</span>
                <strong>{selected.has_api_key ? "API Key 已保存" : "No auth / Keyless"}</strong>
                <span>{selected.has_api_key ? "Windows Credential Manager" : "无持久化密钥"}</span>
              </div>
              <span className={"credential-state " + (selected.has_api_key ? "ok" : "neutral")}>
                {selected.has_api_key ? "Secure" : "Keyless"}
              </span>
            </div>

            <div className="capability-summary">
              {capabilityPills(selected.capabilities).map((pill) => <span key={pill}>{pill}</span>)}
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
              <div>
                <span>Timeout</span>
                <strong>{selected.timeout_s ? String(selected.timeout_s) + "s" : "Runtime default"}</strong>
              </div>
            </div>

            {modelDetail && <div className="model-discovery-result">{modelDetail}</div>}
            {models.length > 0 && (
              <div className="model-discovery-list">
                {models.slice(0, 12).map((item) => <span key={item} className="mono">{item}</span>)}
                {models.length > 12 && <span>+{models.length - 12}</span>}
              </div>
            )}

            <div className="settings-actions test-connection-row">
              <button className="primary" onClick={() => void testSelected()} disabled={busy}>
                Test Connection
              </button>
              {testResult && <span className="test-result">{testResult}</span>}
            </div>

            <div className="credential-actions">
              {!credentialMode ? (
                <>
                  <button onClick={() => setCredentialMode(true)} disabled={busy}>
                    {selected.has_api_key ? "更换 API Key" : "添加 API Key"}
                  </button>
                  {selected.has_api_key && (
                    <button onClick={() => void clearCredential()} disabled={busy}>清除 Key</button>
                  )}
                </>
              ) : (
                <>
                  <input
                    type="password"
                    autoComplete="off"
                    value={replacementKey}
                    onChange={(event) => setReplacementKey(event.target.value)}
                    placeholder="新 API Key"
                  />
                  <button
                    className="primary"
                    onClick={() => void replaceCredential()}
                    disabled={busy || !replacementKey.trim()}
                  >
                    保存新 Key
                  </button>
                  <button
                    onClick={() => {
                      setCredentialMode(false);
                      setReplacementKey("");
                    }}
                    disabled={busy}
                  >
                    取消
                  </button>
                </>
              )}
            </div>

            <div className="provider-danger-zone">
              <div>
                <strong>删除 Provider</strong>
                <span>删除 profile；若这是最后一个 profile，同时删除对应 Credential Manager 凭据。</span>
              </div>
              <button
                className={deleteConfirm ? "danger" : ""}
                onClick={() => void deleteSelected()}
                disabled={busy}
              >
                {deleteConfirm ? "确认删除" : "删除…"}
              </button>
              {deleteConfirm && (
                <button className="link-button" onClick={() => setDeleteConfirm(false)} disabled={busy}>
                  取消
                </button>
              )}
            </div>

            <div className="settings-note">
              账号登录只在 Provider Catalog 注册了正式第三方 OAuth / Device Flow adapter 后出现。
              当前不会导入浏览器 Cookie、复用 Codex/Claude Code OAuth client 或提取消费者会话 Token。
            </div>
          </>
        )}
      </section>
    </div>
  );
}
