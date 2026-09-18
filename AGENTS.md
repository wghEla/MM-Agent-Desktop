# MM-Agent Desktop — Agent 工作规则

本项目是 `MM-Final-Skill`（qybaihe）论文铸造厂能力的 Windows 桌面客户端 + 自研 Agent Runtime 复现。
**最高规格是仓库根的 `00_MM_AGENT_MASTER_PLAN.md`**（原文件 `MM-Agent-Desktop_长期自治开发总方案.md` 与之同源）。

## 上下文恢复序列（每次接手/压缩后必做，禁止重新设计项目）

1. 读本文件
2. 读 `docs/CURRENT_STATE.md`（当前版本、进行中步骤、下一步）
3. 读 `docs/PROJECT_PLAN.md`（版本路线）
4. 读 `docs/spec/FIDELITY_MATRIX.md` + `docs/spec/KNOWN_DEVIATIONS.md`
5. 读最近一个 `docs/runs/vX.Y.0.md` 与 `docs/runs/RUN_LOG.md` 末尾
6. `git status` / `git log --oneline -5`
7. 只读取当前 TODO 涉及的文件，继续干活

## 铁规则

- **只读参考**：`.reference/` 是 gitignored 只读规格快照（SHA 见 `docs/spec/SOURCE_SNAPSHOT.md`）。
  禁止复制其源码/提示词进本仓库；clean-room 重写；行为差异必须登记 `KNOWN_DEVIATIONS.md`。
- **SQLite 是唯一状态真相**；JSON/Markdown 只是可读 carrier。append-only events。
- **LLM 输出不可信**：一切产物过 schema/权限/verifier；Task 成功由 Runtime 判定，不由模型宣告。
- **诚实性**：implemented / unit-tested / mock-provider-tested / integration-tested / E2E-tested /
  real-provider-tested / unverified 七档如实标注。禁止伪造外审、测试、benchmark。
- **密钥纪律**：API key 不进 Git/prompt/event/log/report/导出；正式版用 Windows Credential Manager。
- **每版本循环**：PLAN→IMPLEMENT→UNIT→INTEGRATION→FAILURE INJECTION→SELF REVIEW→更新
  FIDELITY MATRIX→DOCS→REVIEW PACKET→GPT-5.6 Sol High 外审（内置浏览器，质量优先不省 token）→
  TRIAGE→FIX P0/P1→REGRESSION→FINAL VERIFY→COMMIT→TAG→UPDATE CURRENT_STATE→下一版（自动，不停）。
- **外审协议**：security-minded OSS maintainer 视角；P0/P1/P2 分类；P0/P1 未清不 tag；
  大改后 focused re-review；外审原文存 `docs/reviews/vX.Y.0-external-review.md`。
- **文档纪律**：`RUN_LOG.md` append-only；重要设计决定写 `docs/decisions/ADR-*.md`；
  不把只存在于对话上下文里的决定当已决定。
- **开发环境**：仓库 `.venv`（uv 管理，Python 3.11）；不碰用户既有 Python；
  工具发现（XeLaTeX/MATLAB）由 Environment 层做，Agent 不猜路径。
- **用户全局规则**：默认只读；除本长任务授权范围（本仓库内开发写入）外不创建/修改文件；
  ZCode 自身数据放 `D:\dev\AI_harness`，不写 C 盘。

## 版本路线（固定，详见 PROJECT_PLAN.md）

v0.1.0 Kernel → v0.2.0 Windows Workspace/Process/Permission → v0.3.0 Providers →
v0.4.0 S0/G0/S1/G1 → v0.5.0 S2/G2/RedTeam/DAG → v0.6.0 S3/S4/G3/G4/工具链 →
v0.7.0 S5 Arena/Ledgers/Guards → v0.8.0 S5a/S5b/G5/S6/Delivery → v0.9.0 Desktop UI/Packaging →
v1.0.0 Hardening/E2E/Final Review。
