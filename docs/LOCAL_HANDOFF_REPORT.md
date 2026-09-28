# LOCAL_HANDOFF_REPORT — gpt/fidelity-rebuild 本地验证交接

最后更新：2026-09-28（UI v2 Phase-1 Local Validation 之后）

## 当前状态一览

| 门 | 状态 | 报告 |
|---|---|---|
| Source / Pipeline | GO | docs/reviews/（round 系列收口） |
| Windows Package | PASS | docs/runs/installed-* |
| Installed Cancellation | PASS | docs/reviews/v1.0.0-rebuild-*.md |
| Installed Credential | PASS | docs/runs/installed-credential/ |
| Real Provider（Groq gpt-oss-20b） | CONDITIONAL PASS | docs/runs/real-provider/ |
| **UI v2 Phase-1（本轮）** | **PASS（不宣布 Product Release GO）** | docs/reviews/v1.0.0-rebuild-ui-v2-local-validation.md |

最近提交前的本地状态：HEAD `f317663` + UI v2 验证改动（原生选择器/版本对齐/B007）。
测试：464 passed / 0 failed，Ruff clean，前端 build OK，安装版 --startup-smoke exit 0。

## 本轮（UI v2）本地验证做了什么

1. Stage 1 编译：npm ci + build（32 modules）零错误，未回退 GPT 的 UI v2 源码。
2. Stage 2 视觉验收（真实 Tauri dev 窗口 + computer-use）：1440×900 / ≈1220×740 /
   ≈1040×700 逻辑（显示缩放 200%，等效覆盖高 DPI）；三栏/中心主导/无溢出/省略号/
   StageRail 色彩语义（G1 红 FAIL、S0/S1/G0 绿）/深色层级/弹窗适配 全 PASS；
   3 项 P3 化妆 nit 登记未改。证据 dev-A…dev-M 于 docs/runs/ui-v2/。
3. 功能验证（keyless scripted relay 127.0.0.1:28901）：Provider 全流程 + Test Connection
   chat 回退；真实运行到 G1 fail-closed（缺 交接/计划.json）如实红显；控制门控矩阵；
   运行历史只读；Artifact text/JSON/PNG/PDF（WebView2 内嵌渲染实测）；Recent 书签跨重启。
4. Windows 原生目录/文件选择器（本轮实现）：官方 tauri-plugin-dialog（npm
   @tauri-apps/plugin-dialog + Cargo crate + main.rs 注册 + capabilities/default.json 仅
   dialog:allow-open）；ProjectPanel 选择器优先 + "高级：手动路径"折叠保留；ImportPanel
   多选文件按钮；非 Tauri 环境优雅降级。原生 IFileDialog 实测全链路通过。
5. 回归：npm build ✓ / ruff ✓ / pytest 464 ✓。
6. 重打包：sidecar（PyInstaller）重建 + tauri build --bundles nsis + 静默重装至
   D:\dev\MM-Agent-Desktop-release-smoke + --startup-smoke exit 0。

## 已知坑（本轮新登记）

- Tauri release 构建会拒绝 npm 包与 Rust crate 的 minor 不一致（如 @tauri-apps/api 2.12
  vs tauri 2.11）——`npm install` 新插件时可能顺带升级 api，务必对齐（当前 2.11.1/2.7.3）。
- 截图证据管线：ZCode 内置 Read→CDN 通道存在同路径缓存，验收截图须走 computer-use
  getScreenshot 落盘 + 视觉模型 analyze_image（URL 每次唯一）双轨。

## 下一步（建议顺序）

1. GPT-5.6 Sol 外审（同一会话追加）：UI v2 phase-1 + 本轮 diff（重点：picker 权限面、
   ProjectPanel 状态、无第二状态机）。
2. UI v2 phase-2 剩余：workspace file tree、first-run onboarding、project/open 对话框细化。
3. Real Provider 遗留：一次礼节性 G0 全绿 run（复用 Groq key，仅 Credential Manager）。
4. phase-3/4（provider UX 深化 + 最终 local validation）后，才进入 Product Release 讨论。

## 纪律提醒（不变）

- SQLite 唯一真相；LLM 输出不可信；fail-closed 不许为测试绿放松。
- key 不进 Git/prompt/event/log/report/导出；真实 key 只住 Credential Manager。
- RUN_LOG append-only；外审原文归档 docs/reviews/；不伪造任何测试/评审。
