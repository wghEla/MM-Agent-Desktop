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
