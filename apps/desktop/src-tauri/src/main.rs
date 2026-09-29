// MM-Agent Desktop — thin Tauri shell around the authoritative Python runtime.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use rand::RngCore;
use reqwest::Method;
use serde::Serialize;
use serde_json::Value;
use std::env;
use std::io;
use std::net::TcpListener;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tauri::{Manager, State};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

const TOKEN_ENV: &str = "MMAGENT_SIDECAR_TOKEN";

enum SidecarProcess {
    DevelopmentPython(Child),
    Bundled(CommandChild),
}

struct SidecarBridge {
    endpoint: String,
    token: String,
    child: Mutex<Option<SidecarProcess>>,
}

#[derive(Serialize)]
struct BackendResponse {
    status: u16,
    body: Value,
}

impl SidecarBridge {
    fn launch(app: &tauri::AppHandle) -> Result<Self, String> {
        let port = allocate_port().map_err(|e| format!("分配 sidecar 端口失败: {e}"))?;
        let token = random_token();
        let endpoint = format!("http://127.0.0.1:{port}");

        // Debug builds intentionally retain the Python-module path for fast
        // iteration. Release builds use both the frozen API sidecar and a
        // separately bundled managed Python runtime for model-authored scripts.
        let child = if cfg!(debug_assertions) {
            SidecarProcess::DevelopmentPython(spawn_development_python(port, &token)?)
        } else {
            let managed_python = managed_python_path(app)?;
            SidecarProcess::Bundled(spawn_bundled_sidecar(
                app,
                port,
                &token,
                &managed_python,
            )?)
        };

        let bridge = Self {
            endpoint,
            token,
            child: Mutex::new(Some(child)),
        };
        bridge.wait_ready()?;
        Ok(bridge)
    }

    fn wait_ready(&self) -> Result<(), String> {
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_millis(400))
            .build()
            .map_err(|e| format!("构造 sidecar 健康检查客户端失败: {e}"))?;
        let health = format!("{}/health", self.endpoint);

        for _ in 0..80 {
            {
                let mut guard = self
                    .child
                    .lock()
                    .map_err(|_| "sidecar child lock poisoned".to_string())?;
                if let Some(SidecarProcess::DevelopmentPython(child)) = guard.as_mut() {
                    if let Ok(Some(status)) = child.try_wait() {
                        return Err(format!("Python sidecar 提前退出: {status}"));
                    }
                }
            }

            if let Ok(response) = client.get(&health).bearer_auth(&self.token).send() {
                if response.status().is_success() {
                    return Ok(());
                }
            }
            thread::sleep(Duration::from_millis(100));
        }

        self.shutdown();
        Err("Python sidecar 在启动窗口内未通过健康检查".to_string())
    }

    fn shutdown(&self) {
        // Normal desktop exit is not a crash: ask FastAPI/Uvicorn to exit so its
        // lifespan can pause unfinished runs and close project DBs cleanly.
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_millis(800))
            .build()
            .ok();

        if let Some(client) = client.as_ref() {
            let _ = client
                .post(format!("{}/shutdown", self.endpoint))
                .bearer_auth(&self.token)
                .send();

            // Give the server a bounded grace period. A failed health request is
            // sufficient evidence that the loopback listener has gone away.
            for _ in 0..30 {
                let alive = client
                    .get(format!("{}/health", self.endpoint))
                    .bearer_auth(&self.token)
                    .send()
                    .is_ok();
                if !alive {
                    break;
                }
                thread::sleep(Duration::from_millis(100));
            }
        }

        let Ok(mut guard) = self.child.lock() else {
            return;
        };
        let Some(process) = guard.take() else {
            return;
        };

        match process {
            SidecarProcess::DevelopmentPython(mut child) => {
                if !matches!(child.try_wait(), Ok(Some(_))) {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
            SidecarProcess::Bundled(child) => {
                // kill() is a last-resort fallback. If graceful shutdown already
                // ended the process, the error is harmless and intentionally ignored.
                let _ = child.kill();
            }
        }
    }
}

impl Drop for SidecarBridge {
    fn drop(&mut self) {
        self.shutdown();
    }
}

fn spawn_development_python(port: u16, token: &str) -> Result<Child, String> {
    let python = env::var("MMAGENT_PYTHON").unwrap_or_else(|_| "python".to_string());
    Command::new(&python)
        .args([
            "-m",
            "mmagent.sidecar.server",
            "--port",
            &port.to_string(),
        ])
        .env(TOKEN_ENV, token)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| {
            format!(
                "启动开发态 Python sidecar 失败 ({python}): {e}. 可用 MMAGENT_PYTHON 指向项目 Python 3.11。"
            )
        })
}

fn managed_python_path(app: &tauri::AppHandle) -> Result<String, String> {
    let path = app
        .path()
        .resource_dir()
        .map_err(|e| format!("解析应用资源目录失败: {e}"))?
        .join("runtime")
        .join("python.exe");
    if !path.is_file() {
        return Err(format!("内置受管 Python 缺失: {}", path.display()));
    }
    path.into_os_string()
        .into_string()
        .map_err(|_| "内置受管 Python 路径不是合法 Unicode".to_string())
}

fn spawn_bundled_sidecar(
    app: &tauri::AppHandle,
    port: u16,
    token: &str,
    managed_python: &str,
) -> Result<CommandChild, String> {
    let command = app
        .shell()
        .sidecar("mmagent-sidecar")
        .map_err(|e| format!("解析内置 sidecar 失败: {e}"))?
        .args(["--port", &port.to_string()])
        .env(TOKEN_ENV, token)
        .env("MMAGENT_PYTHON", managed_python);

    let (mut events, child) = command
        .spawn()
        .map_err(|e| format!("启动内置 Python sidecar 失败: {e}"))?;

    // Drain stdout/stderr/termination events so the plugin's event channel never
    // becomes the lifecycle bottleneck. Runtime state remains in SQLite/API.
    tauri::async_runtime::spawn(async move {
        while events.recv().await.is_some() {}
    });
    Ok(child)
}

fn allocate_port() -> io::Result<u16> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    Ok(listener.local_addr()?.port())
}

fn random_token() -> String {
    let mut bytes = [0_u8; 32];
    rand::rng().fill_bytes(&mut bytes);
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn validate_backend_path(path: &str) -> Result<(), String> {
    if !path.starts_with('/')
        || path.starts_with("//")
        || path.contains("://")
        || path.contains('\\')
        || path.contains("..")
    {
        return Err("非法 backend path".to_string());
    }
    Ok(())
}

#[tauri::command]
async fn backend_request(
    state: State<'_, SidecarBridge>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<BackendResponse, String> {
    validate_backend_path(&path)?;

    let method = Method::from_bytes(method.to_ascii_uppercase().as_bytes())
        .map_err(|_| format!("不支持的 HTTP method: {method}"))?;
    if method != Method::GET && method != Method::POST {
        return Err("Desktop bridge 当前只允许 GET/POST".to_string());
    }

    let client = reqwest::Client::new();
    let mut request = client
        .request(method, format!("{}{}", state.endpoint, path))
        .bearer_auth(&state.token);
    if let Some(payload) = body {
        request = request.json(&payload);
    }

    let response = request
        .send()
        .await
        .map_err(|e| format!("sidecar 请求失败: {e}"))?;
    let status = response.status().as_u16();
    let bytes = response
        .bytes()
        .await
        .map_err(|e| format!("读取 sidecar 响应失败: {e}"))?;
    let body = serde_json::from_slice::<Value>(&bytes)
        .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(&bytes).into_owned()));

    Ok(BackendResponse { status, body })
}

fn main() {
    let startup_smoke = env::args().any(|arg| arg == "--startup-smoke");

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(move |app| {
            let sidecar =
                SidecarBridge::launch(app.handle()).map_err(io::Error::other)?;
            app.manage(sidecar);

            if startup_smoke {
                // Prove the installed release can resolve bundled resources,
                // start the authenticated sidecar, and pass its health check.
                // Exit shortly after setup so CI does not need an interactive desktop.
                let handle = app.handle().clone();
                thread::spawn(move || {
                    thread::sleep(Duration::from_millis(150));
                    handle.exit(0);
                });
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_request])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                app.state::<SidecarBridge>().shutdown();
            }
        });
}

#[cfg(test)]
mod tests {
    use super::validate_backend_path;

    #[test]
    fn backend_path_is_loopback_relative_only() {
        assert!(validate_backend_path("/health").is_ok());
        assert!(validate_backend_path("/projects/abc/runs").is_ok());
        assert!(validate_backend_path("https://evil.example").is_err());
        assert!(validate_backend_path("//evil.example/x").is_err());
        assert!(validate_backend_path("/../secrets").is_err());
        assert!(validate_backend_path(r"/projects\escape").is_err());
    }
}
