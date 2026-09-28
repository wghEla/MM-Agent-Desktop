# UI v2 Local Validation — Evidence Index (2026-09-28)

全部为真实 Tauri dev 窗口截图（computer-use 屏幕级捕获，窗口矩形精确），无任何真实
密钥或用户数据。验证环境：Windows 11，显示缩放 200%，逻辑 1440×900 ≈ 物理 2880×1800。

| 文件 | 内容 | 清单对应 |
|---|---|---|
| dev-A-welcome-1440.png | Welcome 态 @1440×900：三栏、左项目卡、中间欢迎、右 ARTIFACTS 空态 | A（welcome） |
| dev-B-three-pane-1440.png | 三栏工作台 + 真实运行 run_1837a82a542b：S0/S1 绿、G0 PASS、G1 FAIL（fail-closed 缺 交接/计划.json）、FAILED 总态、控制按钮禁用 | B（three-pane） |
| dev-C-stage-rail-dashboard.png | B 的中心栏聚焦裁剪：StageRail + Run Dashboard（阶段/Tasks/Gates/最近事件） | C（stage rail + dashboard） |
| dev-D-provider-existing.png | Provider 详情：Keyless 状态卡、Protocol/Model/Endpoint/Reasoning、Test Connection "✓ models 端点 501; chat fallback 成功"、OAuth 边界说明 | D（provider existing） |
| dev-E-provider-add-preset.png | 添加表单：7 预设网格、API Key password 框+不回显提示、名称/Model ID、Advanced 折叠 | E（add/preset） |
| dev-F-provider-advanced.png | Advanced 展开：协议=OpenAI Compatible（预设生效）、Base URL 已填、Reasoning、capability 复选 | F（advanced） |
| dev-G-artifact-image.png | Artifact Dock：IMAGE 预览（合成收敛曲线 PNG，非 runtime 产物） | G（image preview） |
| dev-G2-artifact-pdf.png | Artifact Dock：PDF 内嵌预览（WebView2 Edge PDF 查看器渲染合成 PDF） | G（PDF preview） |
| dev-H-1280x800.png | ≈1220×740 逻辑窗口：三栏不挤压、rail 完整、PDF 预览可用 | H（1280 window） |
| dev-I-1100px.png | ≈1040×700 逻辑窗口：下限压力测试，全部元素在位 | 附加（~1100px） |
| dev-J-welcome-recent.png | 欢迎页"最近工作区"书签（UI验收工作区） | 附加（recent） |
| dev-K-restart-recent.png | 应用完全重启后书签仍在（localStorage 持久化） | 附加（restart persistence） |
| dev-L-folder-dialog.png | 原生 Windows 文件夹选择对话框（标题=选择工作区文件夹，tauri-plugin-dialog） | 附加（native picker） |
| dev-M-picker-filled.png | 选择器返回后：路径回填 + 项目名自动推导 + 创建/打开激活 | 附加（picker result） |

配套报告：`docs/reviews/v1.0.0-rebuild-ui-v2-local-validation.md`。
运行环境说明：relay 为本地脚本端点（127.0.0.1:28901，keyless），不持有任何真实凭据；
G/G2 使用的 PNG/PDF 为人工合成测试文件（文件名注明 _测试 / synthetic），非 runtime 宣告产物。
