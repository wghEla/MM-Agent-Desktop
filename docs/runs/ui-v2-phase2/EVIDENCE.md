# UI v2 Phase-2 Local Validation — Evidence Index (2026-09-28)

全部为真实 Tauri dev 窗口截图（computer-use 窗口级捕获），无任何真实密钥/私人端点。
测试工作区：`D:\dev\AI_harness\ui-v2-phase2-create`；relay：本地 keyless scripted relay
（127.0.0.1:28901，长原型模式），不持有任何真实凭据。

| 文件 | 内容 | 协议条目 |
|---|---|---|
| dev-A-welcome-onboarding.png | Welcome 三步 onboarding（1 工作区/2 模型/3 材料）+ 新建/打开主操作 + Recent 带 × 移除 | A |
| dev-B-create-dialog.png | 新建工作区 Dialog：选择文件夹/项目名称/档位/高级手动路径/创建禁用态 + 边界文案 | B |
| dev-C-create-error.png | 重复创建 → "409: 目标目录已有工作区结构: D:\dev\AI_harness\ui-v2-phase2-create" 显示在 Dialog 内且不关闭 | C |
| dev-D-open-dialog.png | 打开工作区 Dialog：空目录 → "400: 不是 mmagent 工作区（缺 project.db）" 留在 Dialog | D |
| dev-E-tree.png | FILES 工作区文件树：输入/题目/problem.md、论文/test.pdf、求解/test.png+test.bin；.mmagent 不出现；目录优先排序 | E |
| dev-F-text-preview.png | tree 点 problem.md → TEXT 预览 + 顶部相对路径 输入/题目/problem.md | F |
| dev-G-pdf-preview.png | tree 点 test.pdf → PDF 内嵌查看器渲染 | G |
| dev-G2-image-preview.png | tree 点 test.png → 图像预览；BIN 显示"不提供内嵌预览 26 B" | G 补充 |
| dev-H-import-autorefresh.png | 原生文件选择器导入 附件_v2.csv → 未手动刷新 tree 自动出现（workspaceRevision） | H |
| dev-I-setup-no-provider.png | 工作区 setup checklist：1·工作区 ✓ / 2·模型 配置→ / 3·材料 + "Runtime 继续 Gate 检查"边界文案 | I |
| dev-J-setup-with-provider.png | 配好 keyless relay 后："✓ 2·模型 Provider 已配置" + ▶启动激活 | J |
| dev-K-recent-remove.png | × 移除 ui-v2-pick-test 后 Recent 3→2（磁盘上工作区与 .mmagent/project.db 完好） | K |
| dev-L-1280x800.png | ≈1220×740 逻辑窗口：tree+import+历史三卡左栏不挤、中心 dashboard、右栏 artifacts | L |
| dev-M-live-refresh.png | RUNNING 期 Artifact dock 自动出现 Runtime 新文件（原型/cancel_probe_*），problem.md 预览保持 | 附加（live polling + preview stability） |
| dev-N-restart-recent.png | 应用完全重启后 Recent 仍 2 条（移除的不复活） | 附加（restart persistence） |
| dev-O-1100px.png | ≈1040×700 逻辑窗口下限压力：399 个 AX 元素全在位 | 附加（~1100px） |

配套报告：`docs/reviews/v1.0.0-rebuild-ui-v2-phase2-local-validation.md`。
合成文件说明：test.pdf/test.png/test.bin/problem.md/data.csv 为人工合成预览冒烟文件
（文件名含 test/_测试/synthetic），非 runtime 宣称产物；G0 曾因附件清单未覆盖 data.csv
正确 fail-closed（Runtime 真理，后为长原型场景移除该文件）。
