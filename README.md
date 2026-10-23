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
- [x] 第 3 步 产品库、推荐、BOQ：箱体 / 控制器 / 处理器只从产品库选（首选优先，已停用不选），产品库编辑另存新版本；BOQ 数量全部来自规则；控制器不够时阻断（产品目前是示例数据）。CR-6 起不含价格：客户版 BOQ（按模板出汇总行，可改，改数量要写原因，可导出 Excel），明细留在内部
- [~] 第 4 步 读文件（服务器端）与确认关：上传后自动读取（PDF 文字层 / 扫描件和图片文字识别 / Excel 按栏名 / DXF；DWG 需装 ODA 转换器），认出的字段带置信度和原文截图；Medium / Low 逐项确认之前不计算。目前用自制样本验证（`docs/step4-识别记录.md`），等真实样本（清单 G1、G2）实测
- [x] 第 5 步 Diagram L1/L2 与 PDF / JPG 标注：示意图由 BOQ 生成，每台设备、每条线缆都标出对应的 BOQ 行（业主提供 / 随设备附带的单独标出）；在 PDF 页面或照片上标点、区域、设备、文字，可设比例，保存时另存标注副本（JPG），原件不动
- [ ] 第 6 步 Proposal 输出、审核、Rev 对比

## 上线与试用

- 服务器安装（给 IT）：Windows 安装包，从 [Releases](https://github.com/JimmyLi09/AV-Proposal-Platform/releases/latest) 下载，步骤见 `docs/服务器装机流程.md`。更新 = 运行新版安装包。
- 安装包由 GitHub Actions 生成（`.github/workflows/windows-installer.yml`、`installer/`）：每次推送都在 Windows 上跑全部测试，并实际安装、更新、卸载一遍。发布新版本：GitHub 网页 Releases → Draft a new release → 新建标签（例 `v0.5.0`，目标 `main`）→ Publish，约 5 分钟后安装包会自动附到这个 Release 上。
- 服务器自己的设置（资料目录、ODA 路径）写在 `app/config/deploy.local.yaml`，由安装程序写入，不进 git。
- 试用整套流程：`docs/试用清单.md`。
