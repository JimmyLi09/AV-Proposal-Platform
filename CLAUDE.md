# AV Proposal Platform · V1 — 开发说明（给 Claude Code）

Audax 内部的**售前 Proposal 生成平台**（不是报价工具）。V1 覆盖两条业务线：**LED** 和 **投影单面融合墙**。
产品负责人：Jimmy（PM，新加坡）。有疑问先问 Jimmy，不要自己猜。

## 先读这些
1. `docs/platform-plan-v1.md` — 完整平台方案（范围、页面、规则 F1–F16 / P1–P13、数据对象、Rev、部署、开发顺序）。**这是需求的唯一来源。**
2. `docs/prototype/` — 23 页可点原型（`*.dc.html` + `canvas.json`）。在线版：https://claude.ai/artifact/CBfKgWjwHyagU1sMhQfAch 。`UI-SPEC.md` 是双语和配色规范。原型只定界面和流程，**不是可复用的前端代码**。
3. `tests/fixtures/regression_cases.json` — 两组金标准：LED（143-Royal Plaza）和投影（114 Showroom）。规则引擎必须算出完全一致的结果。

## 硬约束（不能违反）
- **不接入任何云端 LLM / AI 平台**，不产生额外订阅费用。只用免费 / 开源组件。
- **数量一律由确定性规则引擎计算**，模型（OCR）只负责识别文字和尺寸，绝不计算数量。
- 每个数字都可追溯：公式（代入数值）、规则编号与版本、参数来源、置信度。
- 中央库在**公司服务器 192.168.1.241:8081**，仅公司内网使用，不开公网链接；防火墙只开 Domain + Private。服务器可以上公网装包 / 更新。
- 原始文件永不覆盖；标注、转换都另存副本。
- 不与 Project Platform（192.168.1.241:3000）共用数据库，只通过项目编号关联；项目可先建、后补编号。
- 轻账号：选名字登录，无密码无权限；可以自审自己的 Rev（记录审核人和时间）。
- Rev 锁定 6 样：确认后的输入、规则版本、产品库版本、Cost 快照、模板版本、生成文件。锁定后永不重算，改动开新 Rev。
- 两道关：确认关（Medium/Low 置信度字段逐个确认后才能计算）；审核关（批准后才能正式导出，须联网）。
- 离线时 Local Agent 用缓存规则可算、可标注、可存草稿；不能审核、不能正式导出、不能改库。
- 系数、常量、产品、模板全部**界面可编辑并带版本**；IT 不改 `app/config/*.yaml`（yaml 只放部署配置）。
- 界面中英双语：标签写「English 中文」，说明句只写中文（见 `docs/prototype/UI-SPEC.md`）。品牌按 Audax VI，平台名 AV Proposal Platform。
- 显卡不考虑（OCR 必须能在普通办公电脑 CPU 上跑）。
- V1 不做：DWG 自动出图 / DXF 输出、RCP、施工接线图（Level 3）、自动报价 / Markup、多人同时编辑、完整 B 模式、修改原 CAD、互动投影、多面 / 弧幕 / 地面 / 模型投影。

## 技术选型（建议，第 0 步先和 Jimmy 确认）
方案文档没有锁定技术栈。以下是满足约束的默认建议，开工前确认：
- 服务器：Python 3.12 + FastAPI；PostgreSQL（或先用 SQLite，后迁移）；文件存服务器资料目录。
- 前端：React + Vite + TypeScript，一套代码，服务器提供，Local Agent 也打包一份（离线可用）。
- Local Agent：Windows 托盘程序（Python + pystray，PyInstaller 打包），只监听 127.0.0.1；OCR 用本地 PaddleOCR 或 Tesseract（CPU）；DWG→DXF：有 AutoCAD 用 accoreconsole，没有就用免费 ODA File Converter。
- 输出：PDF（HTML 模板 + 无头 Chromium 或 WeasyPrint）、Word（python-docx）、JPG Boards。
- 需要 Jimmy / IT 确认：服务器操作系统、是否允许装 PostgreSQL、备份位置（清单 A9–A11）。

## 开发顺序（每步完成都要通过验收再进下一步）
1. 数据底座：数据库、文件存储、轻账号、项目与 Rev 骨架。验收：能建项目、传文件，原件无法被覆盖。
2. 规则引擎框架 + LED F1–F16：规则可编辑、带版本、结果可展开公式；框架按业务线分。验收：`regression_cases.json` 的 LED 用例全部通过，含尺寸吸附（4500 → 4480 / 4800）。
3. 产品库、推荐、BOQ、Cost（单价人工录入，过期标红）。验收：推荐全部来自产品库；控制器带载不够时阻断。
4. Local Agent：读文件、OCR 识别文字与尺寸、确认关、独立运行。验收：样本文件逐个记录识别结果；未确认字段无法进入计算。
5. Diagram L1/L2 与 PDF / JPG 标注。验收：示意图里每台设备都能在 BOQ 中找到。
6. Proposal 输出、审核、Rev 对比。验收：一个真实 LED 项目从上传走到批准导出。→ LED V1 可上线。
7. 投影 P1–P13 与投影产品库（镜头是独立产品类）。验收：`regression_cases.json` 的 114 用例全部通过（5 台、0.5 镜头、融合带 ≈ 1.02 m、≈ 7854 px、2.3 mm）。
8. 投影专属图（立面融合区、平面机位、剖面遮挡）与投影 Proposal。验收：用 147-Senja Close 实跑一遍，与工程侧人工计算逐条对比。

## 工作方式
- 先写测试再写规则：每条规则一个单元测试，金标准用例做回归测试，改任何系数都必须跑回归。
- 标「示例值 sample」的常量会被 Jimmy 的真实数据替换：替换时同步更新 fixture，并在提交说明里写明。
- 未定的数据（见方案「待填数据与已知问题」）用示例值推进，界面标黄，不要停工等待。
- 改动保持最小，不加需求外功能；遇到需求不清，停下来问。
