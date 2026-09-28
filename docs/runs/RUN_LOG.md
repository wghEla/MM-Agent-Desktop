# RUN_LOG — append-only 运行日志

> 只追加，不修改历史。格式：`## YYYY-MM-DD HH:MM | 事件`

## 2026-09-19

- 00:40 用户放行。开始执行总方案 §38 前 20 项。
- 00:41 git init（main）+ .gitignore（.reference/ 等）。
- 00:42 clone MM-Final-Skill @ 5f507e0bea0cc1d2f75e60a55fa264c436e2e52d（shallow）。
  首次 checkout 失败：上游 6 个样例文件名含 `:`，NTFS 非法。
  解决：`core.protectNTFS=false` + no-cone sparse-checkout 排除该 6 文件，status 干净。
  记入 KNOWN_DEVIATIONS #13。
- 00:42 clone Mrite @ 72f87c78b3de3ae5d117f2ff89ea363ea3d7173e（shallow）。
- 00:50 环境勘查（只读）：git 2.55 / Python 3.11.9 / uv 0.12.5 / node 24.18 / npm 11.16 /
  cargo 缺（v0.9 前 rustup）/ XeLaTeX 2026 实际路径多一层 texlive / MATLAB v26.1 根目录布局。
  两处发现路径与总方案初稿不符 → KNOWN_DEVIATIONS #5/#6，发现器设计已更新。
- 01:00 规格精读完成（清单见 SOURCE_SNAPSHOT）。关键产出：31 节点流程、门检全判据、
  回路协议全语义、wave 并发语义、红队复算/仲裁/升格/降级语义、S5 十八步、档位表、阈值表、
  铁律 20 条、P1–P10、回流预算表。
- 01:05 spec 四件套 + AGENTS.md + PROJECT_PLAN + ARCHITECTURE + CURRENT_STATE 落盘。
  总方案副本入库为 00_MM_AGENT_MASTER_PLAN.md。
- 01:10 下一步：uv 环境 → mmagent 骨架 → v0.1.0 kernel 实现 → 测试 → baseline + v0.1.0 循环。
- 01:30 v0.1.0 kernel 实现完成（18 模块），40 测试全过。
- 01:35 review packet 发 GPT-5.6 Sol High 外审。R1：3 P0/8 P1/8 P2。
- 01:40-02:20 修复全部 P0/P1/P2（含：SUCCEEDED 强制路径、词法 reparse、host_code 位、
  任务租约 CAS、严格入口、取消统一、事件同事务、artifact 封存、变量注入防护、
  Run 迁移表、finish 幂等、increment 收紧），52→73 测试。
- 02:25 R8 终审 GO。期间 R3-R7 各轮共追加 11 条 P1 全部闭环
  （str.replace 静默未命中事故：改为 assert+getsource 验证）。
- 02:30 tag v0.1.0。
- 01:20 v0.2.0 实现：ProcessManager（Job Object）、EnvironmentManager、17 角色注册表、
  python 工具接入 Job、P2 清理。79→102 测试。
- 01:35 v0.2.0 外审 R1：5 P1（未托管启动窗口/重派时序/kill 谎报/取消三态/输出预算等）。
- 01:50 CREATE_SUSPENDED 原子启动 + per-name 租约 + 三态取消 + 终态原子提交重写，102 测试。
- 02:00 v0.2.0 外审 R2：2 P1（_terminate_tree_state 缺失已修未声明、resume quarantine）。
- 02:05 补 _terminate_tree_state 负向测试 + racer2/rc=-99 区分测试，104 测试。
- 02:10 v0.2.0 外审 R3：3 P1（quarantined 收口/identity 去重/ctor guard）。
- 02:20 remove_quarantined + ManagedProcess ctor 入 guard + racer 测试，106 测试。
- 02:30 v0.2.0 外审 R4（GO 前置）：2 P1（_resolve 未含 registry remove、ctor 前移未落地）。
- 02:40 _resolve 完整 primitive（compare-and-remove）+ ctor 前移落地 + spy 区分测试，107 测试。
- 02:45 v0.2.0 外审 R5：GO（可以 tag）。P2 记录：quarantined 历史积累、HANDLE_LIST v0.3。
- 03:00 v0.3.0 外审 R1：无 P0，多条 P1（image_input 能力虚假/Gemini id/continuation/Retry-After 等）。
- 03:10 全部修复：image_input=False 五协议、anthropic reasoning 空集、gemini id+maxOutputTokens、
  Responses continuation_items、safe_json/parse_retry_after/stop fail-closed、ProviderConfig ref 校验。117→124 测试。
- 03:20 R2：1 P1（parse_retry_after 未接线 429 路径）。修复 + generate() 级集成测试 4 场景。124→129。
- 03:30 R3：GO。tag v0.3.0。
- 09-27 Round2 收口：G5 返工真闭包（图/文强制回执→收回执→逐项裁定 gen CAS→已消解/未消解、
  算路 upsert 降级放行保 S2 条目、每轮台账落盘、有降级记录的存活条目返工耗尽后回搁置）。
- 09-27 S5 熔断升格真实化：必选回执 artifact、started/succeeded/failed 事件按状态落账、
  运行时收回执、每 (id,generation) 一次、终轮熔断必执行；修 len(bool) 崩溃
  （checkpoint.s5_escalation_extension 从未被测试暴露）。
- 09-27 S5 升格耗尽→Runtime 登记 (id,generation) 精确降级放行 + 搁置；G5 端回搁置闭环。
- 09-27 S6 终局：修复后重跑机械 G5 + 新鲜当前 PDF 硬伤终审（S6:出版终审/审稿/S6终审复核.json，
  defect_hunter scope 扩展），两者都过才 harvest。
- 09-27 删手工 append 事件的伪测试，换 run_s5/run_g5_rework/run_s6 真实路径行为测试 8 条。
- 09-27 全量回归 416 passed / 0 failed，Ruff clean。FIDELITY_MATRIX A17/A20/B7/A21 证据更新。
- 09-27 下一步：重生成 review packet → Round 3 外审。
- 09-27 外审阻塞：ChatGPT 会话登出（登录页），Round 3 外审待用户登录后同会话提交。
  转入 PARTIAL 项收口：
- 09-27 B14：S2 checkpoint 重用补下游级联失效——上游问题因任何原因重算（checkpoint 失效或
  崩溃后缺失）时，all_downstreams 闭包内的下游 checkpoint 一律删除并强制重算
  （pipeline.s2_downstream_invalidated 事件）。真实路径测试：仅损坏问题1声明，
  下游自身 G2 仍过也必须重算。
- 09-27 E8：有界编译修复协议 compile_repair.py——编译失败→撰稿腿拿日志改 tex（必须回执）→
  重编译；腿失败或耗尽即 fail-closed。接入 S4 终编译、S5b 初始编译、G5 返工 R51 编译。
- 09-27 B9：结构守卫补 R38③（附录 lstlisting 清单减少）+ R68⑤（正文插图减少且接收章联动）
  + R47 代码章判定；guarded_repair.py 实现 改前快照→腿→结构守卫→违规整份回退+留底
  审稿/回退稿/，接入 G5 返工文路（REVERTED 腿的回执不被受理）。
- 09-27 全量回归 422 passed / 0 failed，Ruff clean。B9/B14/E8 升 MATCH。
- 09-27 Round 3 本地收口：同步 GPT source-only closure 到 f94d08e（33544ec 之后 54 提交），
  按 handoff 执行本地验证。Stage A focused：修 4 个 fixture（S4 定向修订回执、G5 图事务
  writer-sync 腿、S5 升格失败不再给扩展轮、裁定 generation 不再由 Runtime 代填），149 passed。
- 09-27 Stage B：新增 tests/pipeline/test_round3_closures.py 12 条区分性真实路径测试——
  S5 算级联（solver→红队→G2→下游重算→换版清单→绘图→guarded 同步→才收回执）、算失败无回执、
  清单先于同步且同步失败仍留痕、算升格获胜变体 Runtime 晋升为正典真值、图/算回执自证被拒
  （S5+G5）、G5 writer-sync 失败保持 active、Change Guard 整份回退、0.45/0.70 区分、
  守卫快照崩溃恢复、回退即删陈旧回执。调试要点：run_s5 台账只从 checkpoint 事件恢复
  （磁盘 seed 不可见）；终轮不跑返工；红队脚本必须写 复算.json；叙事级问题不阻塞收敛。
- 09-27 Stage C：openai_compatible extra.image_input 三态后端 round-trip 测试
  （True/False/默认 False）+ 前端 checkbox「该兼容渠道支持图片输入」确认存在。
- 09-27 Stage D：全量 439 passed / 0 failed，Ruff clean，前端 vite build 158KB 通过。
- 09-27 FIDELITY_MATRIX：B7/B8/B14/E8 → MATCH（含 HEAD 证据），B9 保持 PARTIAL
  （P2-1 核心结构文件/问题章节数不变量未做），A17/A20 证据刷新仍 PARTIAL。
  提交推送，不 tag，不 merge。下一步 Round 4 外审。
- 09-27 Round 4 本地收口：同步 GPT source-only fixes 到 902abe2（f17d248 后 13 提交）。
  Stage A focused：90 tests，唯一 fixture 回归正是 R4-P1 本身（旧 fixture 故意让失败的图事务
  走文路）——改断言为「排队一个本可成功的 Writer 响应也不被消费 + 回退日志无 G5:R1:文」。
- 09-27 新增 tests/pipeline/test_round4_closures.py 9 条区分性测试：S5 多问题算/图 Issue 一律
  unrouted（零回执、尝试次数不增）、S5 返工后编译/修复先于 round checkpoint（post_rework_compile
  证据 + 编译失败合并为 硬伤/文/编译 且先于 checkpoint 落账）、G5 页数守卫控制返工轮
  （new_pass = page_ok AND hunter，20页 vs 基线10 不再提前 break）、compatible 4xx 正文
  redact_secret 不泄漏 key、reasoning_effort 仅显式能力开启才发送/宣告、profile extra 双能力
  round-trip。
- 09-27 Stage B：全量 448 passed / 0 failed，Ruff clean，前端 build 158.10 kB，
  secret scan 247 文件无真实密钥。A17/A20 保持 PARTIAL（完整 ordering/parity audit 未做），
  B9 保持 PARTIAL（P2-1 结构不变量）。不 tag、不 merge。下一步 GPT-5.6 Sol 终审。
- 09-27 Final source gate 本地验证：同步 GPT final fixes 到 cc46332（c4a38cb 后 11 提交）。
  S6 图修复升级为完整事务（Plotter→Runtime 跑图→guarded Writer 同步 回执_S6_图同步问{q}.json
  →final compile→机械 G5→新鲜可视化终审→harvest），同步失败即 S6 false、无 harvest、
  无 checkpoint.s6_complete；Runtime 机械生成 交付/交付报告.md（降级问题、精确 (id,generation)、
  全部非已消解台账行、运行指标——模型无权隐藏）；compatible Test Connection 增加
  /models 失败→配置模型最小 chat fallback（max_tokens=1、无 reasoning_effort、4xx 脱敏）。
- 09-27 验证结果：focused 20 passed；全量 451 passed / 0 failed（129.9s）；Ruff clean
  （仅 compatible import 排序一处修复）；前端 build 158.10 kB；secret scan 249 文件 clean。
- 09-27 Gate 决定：Source/Pipeline Gate = GO（Round 1-4 + 终审无已知源码级 P0/P1）；
  A12 → MATCH（producer+精确消费+G5 fail-closed+S6 披露 全链条测试证据）；
  A17/A20/B9 保持 PARTIAL；Product Release Gate = HOLD（MSVC/NSIS/安装版取消证明/
  真实 provider smoke/CI 决议/偏差接受 待办）。不 tag、不 merge、不开第五轮泛化。

## 2026-09-28

- 10:50 接手上下文恢复，HEAD 同步至 8ba3231（5 处桌面发行元数据对齐 1.0.0-rebuild.1）。
- 10:55 源码回归验证：`uv run ruff check .` clean；`uv run pytest -q` 451 passed / 0 failed (208.1s)；`apps/desktop` npm ci + npm run build 产物 158.10 kB (vite)。元数据对齐验证通过。
- 11:03 PyInstaller sidecar 构建：`uv run python scripts/build_sidecar.py` 生成 `apps/desktop/src-tauri/binaries/mmagent-sidecar-x86_64-pc-windows-msvc.exe` (40.5MB)，`--help` 验证通过 (exit code 0)。
- 11:13 独立科学计算受管 Python Runtime：修复 `scripts/build_managed_runtime.py` 在存在 local .venv 时的 `uv python find` 隔离路径，打入 CPython 3.11.16 + 39 个数模科学包；`apps/desktop/src-tauri/resources/runtime/python.exe` import 验证输出 `managed-runtime-ok`，生成 `MMAGENT_RUNTIME.json`。
- 12:01 MSVC Build Tools 安装：下载官方 vs_BuildTools.exe，用户 UAC 授权后以 `--installPath D:\dev\msvc --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive --wait --norestart` 安装至 `D:\dev\msvc` (v17.14.37710.0, cl 19.44.35229, link 14.44.35229, MSBuild 17.14.60, Windows SDK 10.0.26100.0)；vcvars64.bat 初始化环境后 cl/link/msbuild/rustc 1.98.1 验证通过。
- 12:21 Tauri Release 构建与 NSIS 打包：`apps/desktop` 执行 `npm run tauri -- build --bundles nsis`，生成：
  - Release 二进制：`apps/desktop/src-tauri/target/release/mmagent-desktop.exe` (12,878,336 字节)
  - NSIS 安装包：`apps/desktop/src-tauri/target/release/bundle/nsis/MM-Agent Desktop_1.0.0-rebuild.1_x64-setup.exe` (158,394,058 字节，内含受管 Python 科学栈与 Sidecar)。
- 12:22 隔离静默安装验证：静默安装至 `D:\dev\MM-Agent-Desktop-release-smoke`，安装器 ExitCode = 0。安装目录中 mmagent-desktop.exe、mmagent-sidecar.exe、runtime/python.exe、uninstall.exe 完备。运行安装版受管 Python 执行科学库 import 验证，输出 `installed-runtime-ok`。
- 12:23 宿主 Python 隔离启动 Smoke 验证：在剥离一切开发态 Python 环境变量 (PATH 仅留 Windows 系统目录，清空 MMAGENT_PYTHON, PYTHONPATH, VIRTUAL_ENV) 的隔离子环境中运行 `mmagent-desktop.exe --startup-smoke`，成功完成随机 loopback token 分配、受管 Python sidecar 启动、带鉴权 `/health` 探活与优雅退出，ExitCode = 0。
- 12:23 孤儿进程检查：Win32_Process 全局扫描确认无任何残留的 mmagent-desktop.exe / mmagent-sidecar*.exe / runtime/python.exe 孤儿进程。
- 12:25 Gate 决议：Windows Product Release Package Gate = PASS；Source/Pipeline Gate = GO；整体 Product Release Gate = PARTIAL / HOLD（待办：Installed Live Cancellation Gate、Real Provider Smoke、CI 决议、偏差最终确认）。

- 09-28 Installed Cancellation Gate：安装版（重打包后）通过产品鉴权取消端点取消真实长任务
  （Runtime 托管 python 父+子 Job Object 树）。0.7s 进入 CANCELLED；父/子进程双亡；0 孤儿；
  finished 标记不存在；进度冻结；无重试/双写者；全新 sidecar 重启后仍 CANCELLED 且无自动恢复；
  取消后新 run 原型任务 SUCCEEDED 并干净 PAUSED。证据 docs/runs/installed-cancellation/。
- 09-28 门内发现并修复两个产品 bug（源码修复→重打包→重装后再跑门）：
  ① WindowsCredentialStore 在当前 pywin32 下不可用（CredWrite 需 str blob / CredRead 返回
  utf-16le）——3 focused tests；② 无 key provider 发送空 `Authorization: Bearer ` 被 httpx
  拒绝——openai_chat/responses 改为省略该头——2 focused tests。全量 456 passed，Ruff clean。
- 09-28 遗留到 Real Provider Gate：冻结 sidecar 内 Credential READ 路径端到端复验
  （写路径已在产品内验证，读 round-trip 由 dev 树单测覆盖）。
- 09-28 Installed Credential Gate：根因为 PyInstaller 漏掉 win32cred 惰性导入的
  win32timezone（旧 get() 把一切读失败伪装成 not found）。修复：build 脚本加
  --hidden-import；credentials.py 引入 CredentialNotFound/CredentialReadError 分级
  + describe() 非机密诊断；sidecar 新增鉴权诊断端点；openai_chat Test Connection
  补 /models-404→配置模型最小 chat fallback。462 passed（新增跨进程/错误分级/fallback
  等测试），Ruff clean，重打包+静默重装+smoke 0。
- 09-28 安装版 E2E（fake secret）：产品边界写 → SQLite 仅存 ref（字节扫描无 secret）
  → 完全退出 → 全新 sidecar 读到（found=true）→ Test Connection 404→fallback 成功 →
  环回 relay 强制校验 Bearer，29 次请求 0 失配，安装版 Runtime 完整跑通 S0+S1 全部
  腿并在 S2 边界干净 PAUSED。测试凭据事后全部从 Credential Manager 删除。
  Installed Credential Gate = PASS；Real Provider = WAITING_FOR_USER_CREDENTIAL。
- 09-28 Real Provider Gate（Groq，openai/gpt-oss-20b）：R1 重启后凭据读取、R2 Test
  Connection 200、R3 真实生成（真实 token 计量）、R4 真实工具调用全部 PASS；image
  N/A；reasoning_effort 为 gpt-oss 在 Groq 的必填参数（400 证实）→ profile 设 low。
  两次 provider 证实的配置修正：llama-3.1-8b-instant 已下线(404)→gpt-oss-20b。
  门内修两个产品 bug：fs.read 读目录 PermissionError 崩腿→干净工具错误；answer_predictor
  读权限缺 数据档案.json（与其腿指令矛盾）。464 passed，重打包重装后所有真实运行均在
  新安装版上执行。S0 双腿多次全 SUCCEEDED（v8/v10 同轮双绿），G0 单轮绿灯被小模型
  schema 方差（英文键/题目≠赛题/坏 JSON）+免费档 429 阻——门每次都正确 fail-closed。
  Real Provider = CONDITIONAL PASS（唯一遗留：一次礼节性 G0 全绿 run）。secret scan
  （gsk_ 模式）267 文件 CLEAN；真实 key 仅存 Credential Manager。
