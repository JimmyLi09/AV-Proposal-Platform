# AV Proposal Platform

Audax 售前 Proposal 生成平台 V1（LED + 投影单面墙）。需求见 `docs/platform-plan-v1.md`，开发约定见 `CLAUDE.md`。

## 本机运行（开发）

需要 Python 3.12、Node.js 22。

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip ...
(cd web && npm install && npm run build)
.venv/bin/python -m app                             # http://localhost:8081
```

改界面时可另开 `cd web && npm run dev`（http://localhost:5173，`/api` 自动转到 8081）。

端口、资料目录在 `app/config/deploy.yaml`。数据库 `avp.db` 和原件都在资料目录里，启动时自动建表 / 升级。

## 测试

```bash
.venv/bin/python -m pytest
```

## 进度

- [x] 第 1 步 数据底座：选名字登录、建项目（编号可后补）、上传原件（只读、同名不覆盖）、Proposal 从 Rev 0 草稿开始
- [x] 第 2 步 规则引擎框架 + LED F1–F16：参数和算式可在界面改（可分档），保存另存新版本；试算可展开算式；金标准 143-Royal Plaza 全部对上
- [x] 第 3 步 产品库、推荐、BOQ、Cost：箱体 / 控制器 / 处理器只从产品库选（首选优先，已停用不选），产品库编辑另存新版本；BOQ 数量全部来自规则；单价人工录入、过期标红；控制器不够时阻断（产品与单价目前是示例数据）
- [~] 第 4 步 读文件（服务器端）与确认关：上传后自动读取（PDF 文字层 / 扫描件和图片文字识别 / Excel 按栏名 / DXF；DWG 需装 ODA 转换器），认出的字段带置信度和原文截图；Medium / Low 逐项确认之前不计算。目前用自制样本验证（`docs/step4-识别记录.md`），等真实样本（清单 G1、G2）实测
- [ ] 第 5 步 Diagram L1/L2 与 PDF / JPG 标注

服务器（192.168.1.241）安装步骤在 LED V1 上线前（第 6 步）写成给 IT 的指引。
