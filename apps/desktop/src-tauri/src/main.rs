// MM-Agent Desktop — Tauri 2 backend shell
// Python Core 通过 HTTP/IPC 交互，GUI 不承载业务状态真相
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
