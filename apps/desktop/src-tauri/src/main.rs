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

const TOKEN_ENV: &str = "MMAGENT_SIDECAR_TOKEN";

struct SidecarBridge {
    endpoint: String,
    token: String,
    child: Mutex<Option<Child>>,
}

#[derive(Serialize)]
struct BackendResponse {
    status: u16,
    body: Value,
}

impl SidecarBridge {
    fn launch() -> Result<Self, String> {
        let port = allocate_port().map_err(|e| format!("分配 sidecar 端口失败: {e}"))?;
        let token = random_token();
        let endpoint = format!("http://127.0.0.1:{port}");
        let python = env::var("MMAGENT_PYTHON").unwrap_or_else(|_| "python".to_string());

        let child = Command::new(&python)
            .args([
                "-m",
                "mmagent.sidecar.server",
                "--port",
                &port.to_string(),
            ])
            .env(TOKEN_ENV, &token)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| {
                format!(
                    "启动 Python sidecar 失败 ({python}): {e}.                      开发态可用 MMAGENT_PYTHON 指向受管 Python；正式包将改为内置 sidecar。"
                )
            })?;

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

        for _ in 0..50 {
            {
                let mut guard = self
                    .child
                    .lock()
                    .map_err(|_| "sidecar child lock poisoned".to_string())?;
                if let Some(child) = guard.as_mut() {
                    if let Ok(Some(status)) = child.try_wait() {
                        return Err(format!("Python sidecar 提前退出: {status}"));
                    }
                }
            }

            if let Ok(response) = client
                .get(&health)
                .bearer_auth(&self.token)
                .send()
            {
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
        let Ok(mut guard) = self.child.lock() else {
            return;
        };
        let Some(child) = guard.as_mut() else {
            return;
        };

        // FastAPI lifespan needs a graceful signal to turn unfinished runs into
        // resumable PAUSED state. On Windows, Child::kill is forceful; until the
        // packaged sidecar has a dedicated shutdown endpoint/signal handler, wait
        // briefly for normal process exit, then kill as a last resort.
        if matches!(child.try_wait(), Ok(Some(_))) {
            *guard = None;
            return;
        }
        let _ = child.kill();
        let _ = child.wait();
        *guard = None;
    }
}

impl Drop for SidecarBridge {
    fn drop(&mut self) {
        self.shutdown();
    }
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
    let body = serde_json::from_slice::<Value>(&bytes).unwrap_or_else(|_| {
        Value::String(String::from_utf8_lossy(&bytes).into_owned())
    });

    Ok(BackendResponse { status, body })
}

fn main() {
    let sidecar = match SidecarBridge::launch() {
        Ok(value) => value,
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(1);
        }
    };

    tauri::Builder::default()
        .manage(sidecar)
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
