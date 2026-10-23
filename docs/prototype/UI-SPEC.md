# AV Proposal Platform 原型 · 双语 + 投影页 编写规范

原型目录：/home/claude/avp-proto/project/ 。每页一个 `*.dc.html`（设计画布页面格式），参照现有页面写法：
- 只用内联 style；`<x-dc>` 包住页面；底部 `<script type="text/x-dc" data-dc-script data-props='{"$preview":{"width":1440,"height":1100}}'>` 里 `class Component extends DCLogic { renderVals(){ return {...} } }`。
- 绑定写 `{{name}}`，条件块 `<sc-if value="{{x}}" hint-placeholder-val="{{ false }}">…</sc-if>`，状态用 `this.state` + `this.setState({...})`，按钮 `onClick="{{fn}}"`。参照 Confirm.dc.html、Agent.dc.html、Preview.dc.html 的交互写法。
- 页面之间用 `<a href="X.dc.html">` 跳转。
- 侧栏、页头、步骤条、子 tab 已经是双语（脚本已替换），新页面直接**复制 Workspace.dc.html 的侧栏和页头原样**（侧栏里 "Proposal Builder" 高亮；库类页面高亮对应菜单项）。
- 布局要自适应：flex-wrap / auto-fit grid，跟现有页面一致。不要横向滚动（表格可放 overflow-x:auto 容器）。

## 配色（Audax）
bg #F5F2EC · 卡片 #FFFFFF · 线 #E6E0D6 / #EFEBE4 · 正文 #1F2430 · 次文字 #6B6558 · 深蓝 #15203A · 橙色主按钮 #C2410C · 绿 #2F7A5B/#E6F2EC · 琥珀 #9A4A12/#FDF1E6 · 红 #B91C1C/#FDE4E4 · 蓝 #2C5AA0/#E8EFF9 · 示例值标签背景 #F1EEE8。

## 2026-10-22 更新：一次只显示一种语言

- 界面右上角有「EN / 中文」切换按钮，默认中文，一次只显示一种语言（见改动单 CR-4）。
- 原型源码里仍按下面的「English 中文」写法录入，由脚本拆成 `<span class="zh">…</span><span class="en">…</span>`，说明句也配了英文。**正式开发请用语言包（zh.json / en.json），不要照搬原型的拆分方式。**
- 以下双语规则仅用于原型录入。

## 双语规则（统一一种样式）
1. **标签类文字写「English 中文」**：页面标题、区块标题、tab、表头、字段名、按钮、状态标签。例：`Confirmed inputs 已确认输入`、`Approve 批准`、`PASS 通过`、`NOTE 提示`、`BLOCK 阻断`。h1 写法：`<h1 ...>LED Recommendation <span style="font-weight: 500; color: #6B6558; font-size: 0.7em">LED 推荐方案</span></h1>`；h2 同理（中文用 `font-weight: 500; color: #6B6558; font-size: 0.85em`）。表头、字段名、按钮直接用空格连接 `English 中文`。
2. **说明类句子只写中文**（提示、帮助文字、风险条目、日志描述等），专有名词保留英文（Rev、BOQ、Proposal、Agent、DWG、PDF 等）。不要把一段话中英各写一遍。
3. 数值、单位、型号、规则编号（F1、P5）、公式原样保留。公式里的变量名可以保持英文。
4. 不改动数字和交互逻辑，只换文字；renderVals 返回的文字也要按上面规则改。

## 投影示例项目（新页面全部用这一组数）
项目：**114-Showroom · PJ-1 展厅投影墙**，Rev 0，规则 v1.3，产品库 v1.0。（这是已完工项目，用来当回归样本和示例。）

已确认输入（Confirm）：
| 字段 | 值 | 来源 | 置信度 |
|---|---|---|---|
| 墙宽 Wall width | 18325 mm | 立面图 DWG | High |
| 墙高 Wall height | 2700 mm | 立面图 DWG | High |
| 可用进深 Available depth | 3200 mm | 平面图 PDF p2 | Medium → 需确认 |
| 天花高度 Ceiling height | 3000 mm | 剖面缺失，手填 | Low → 需确认 |
| 安装方式 Mounting | 吊顶 Ceiling | 手填 | Medium → 需确认 |
| 环境光 Ambient light | ≤ 150 lux（暗场展厅） | 手填 | Low → 需确认 |
| 幕面 Surface | 白色涂料墙，增益 1.0 | 现场照片 | Medium |
| 最近观看距离 Nearest viewing | 1.5 m | 手填 | Low → 需确认 |
| 信号距离 Signal run | 35 m（机柜到投影机） | 平面图 | Medium |
资料齐全度：平面图 ✓、立面图 ✓、剖面图 ✗、天花图 RCP ✗ → B 级。缺剖面会在风险条款里自动加一条。

计算结果（P1–P13）：
- P1 单台画面宽 w = 2.7 × 1.6 = **4.32 m**（16:10，WUXGA 1920×1200）
- P2 台数 n = ceil((18.325 − 4.32) ÷ (4.32 × 0.85)) + 1 = ceil(3.81) + 1 = **5**
- P3 镜头：国产定焦 **0.5**（适配 PT-BHZ611C）；最短距离 0.5 × 4.32 = 2.16 m；进深 3.2 m 放得下。按 2.24 m 装（镜头前端到墙）。
- P4 实际画面宽 w' = 2.24 ÷ 0.5 = **4.48 m**，画面高 4.48 ÷ 1.6 = 2.80 m
- P5 融合带 o = 1 − (18.325 − 4.48) ÷ (4 × 4.48) = **22.7 %**，约 **1.02 m**，在 15–30 % 内 → PASS
- P6 高度覆盖 2.80 ≥ 2.70 → PASS（上下各余 50 mm）
- P7 拼接横向像素 = 5 × 1920 − 4 × 0.227 × 1920 ≈ **7854 px**，纵向 1200 px
- P8 像素尺寸 = 18325 ÷ 7854 ≈ **2.3 mm**；按 1 m/mm，2.3 m 以内会觉得不够清晰；最近观看 1.5 m → **NOTE**（114 验收时确实反映过清晰度不够）
- P9 单台流明需求 = 100 nits × π × (4.48 × 2.80) ÷ 1.0 ÷ 0.8 ≈ **4926 lm**；PT-BHZ611C 示例值 6000 lm → PASS（示例值，参数待补）
- P10 剖面遮挡：机位高 2.8 m、离墙 2.24 m，画面底边在地面；人高 1.8 m 时离墙 **1.44 m 以内**会挡光 → NOTE
- P11 融合器：n = 5 ≥ 2 → **ZWIN 16ch × 1**（输出 16 ≥ 5）→ PASS
- P12 电源：5 × 450 W（示例）+ 播控电脑 500 W = 2.75 kW → **2 路** 2.5 kW 回路；信号 35 m < 50 m → HDBaseT，不用光纤（HDMI 上限待定）
- P13 内容计量：画布 **7854 × 1200 px**；时长、场景数人工填，价格人工填
- 示例目标亮度 100 nits、derate 0.8、增益 1.0 都是示例值（页面上标「示例值 sample」）。

BOQ（投影）：投影机 PT-BHZ611C × 5、国产定焦镜头 0.5 × 5、ZWIN 16ch 融合器 × 1、播控电脑 × 1、HDBaseT 发送/接收 × 5 套、吊架 × 5（视现场）、内容制作（计量 7854×1200，价格人工）。

## 投影 7 个页面（文件名固定）
| 文件 | 页面 | 侧栏高亮 |
|---|---|---|
| ConfirmPJ.dc.html | 2 Confirm Inputs 确认输入（投影） | Proposal Builder |
| WorkspacePJ.dc.html | 3 Recommendation 推荐（投影） | Proposal Builder |
| CalcPJ.dc.html | 3 Calculations 计算依据 P1–P13 | Proposal Builder |
| DiagramPJ.dc.html | 3 Diagram 示意图：立面融合区图、平面机位图、剖面遮挡图、信号链 L1 | Proposal Builder |
| ProductsPJ.dc.html | Product Library 产品库 · 投影 tab | Product Library |
| RulesPJ.dc.html | Rules Engine 规则引擎 · 投影 tab | Rules Engine |
| TemplatesPJ.dc.html | Templates 模板 · 投影 tab | Templates |

投影流程的步骤条：1 → NewProposal.dc.html，2 → ConfirmPJ，3 → WorkspacePJ，4 → Cost.dc.html，5 → Annotate.dc.html，6 → Preview.dc.html（4–6 为共用页）。投影 3 号页的子 tab：Recommendation → WorkspacePJ，Calculations → CalcPJ，Diagram → DiagramPJ。

库类页面（产品库 / 规则 / 模板）顶部加业务线 tab 条（LED 页和投影页都加，互相链接）：
```html
<div role="tablist" aria-label="Business line 业务线" style="display: flex; gap: 6px">
<a href="Products.dc.html" style="padding: 7px 14px; border-radius: 16px; background: #15203A; color: #FFFFFF; font-weight: 600; font-size: 12.5px; text-decoration: none">LED</a>
<a href="ProductsPJ.dc.html" style="padding: 7px 14px; border-radius: 16px; border: 1px solid #E6E0D6; background: #FFFFFF; color: #3B3A36; font-size: 12.5px; text-decoration: none">Projection 投影 · 单面墙</a>
</div>
```
（当前页用深蓝实心样式。）

## 投影常量（RulesPJ 用，均可编辑，带版本）
| 键 | 值 | 状态 |
|---|---|---|
| aspect 单台长宽比 | 1.6 | 已定 |
| overlapMin 融合带下限 | 15 % | 已定（114 验证） |
| overlapMax 融合带上限 | 30 % | 已定 |
| derate 亮度折减 | 0.8 | 示例值 |
| utilMin 最低利用率 | 0.8 | 示例值 |
| targetNits 目标亮度 | 100 nits（≤150 lux） | 示例值，待按环境光分档 |
| minNits 最低亮度 | 50 nits | 示例值 |
| pixelRule 清晰度 | 1 m / mm | 已定 |
| personHeight 遮挡检查人高 | 1.8 m | 已定 |
| circuitKw 回路容量 | 2.5 kW | 已定 |
| fiberOver 光纤阈值 | 50 m | 已定 |
| hdmiMax HDMI 上限 | — | 待定 |
| canvasHeight 内容画布高 | 1200 px | 已定 |

## 投影产品（ProductsPJ 用）
投影机：PU900 9000 lm · PU800 8000 lm · PT-BAZ722 7300 lm · PT-GMZ501CB 5000 lm（超短焦 0.235）· CB-L695SE 6000 lm · CB-C15KU 10000 lm · PT-BHZ611C（参数待补，示例 6000 lm）。
镜头（独立产品类）：国产定焦 0.46 / 0.5 / 0.6 / 0.8，位移 40 % / 15 %，适配机型列表。
融合器 / 软件：ZWIN 16ch；ImmersiveCalibrationPRO v4.3.0 16ch。
单价一律留空或示例，由 Cost 页人工录入。

## 投影模板（TemplatesPJ 用）
章节：Concept 概念 · Recommended Configuration 推荐配置 · Quantity Range & BOQ · System Diagram L1 · Schematic L2 · 专属图（立面融合区、平面机位、剖面遮挡）· Annotated Drawings 标注图 · Risks & Assumptions 风险与假设 · Calculation Basis 计算依据 P1–P13。
4 条固定风险条款：融合带可能偏亮；清晰度受像素尺寸限制；天花过矮影响安装；天花或建筑抖动可能导致融合错位。另有「资料齐全度」条款：缺剖面 / RCP 时自动加入。

## 2026-10-15 追加
- **方案演示稿**：Deck.dc.html（第 6 步审核导出 → Proposal Deck）。封面保留标题、项目名、项目编号、客户、地点；每页 AUDAX 页眉、Confidential 页脚、页码；不显示价格。
- **投影系统与布线**：SystemPJ.dc.html，投影第 3 步第 4 个子 tab「System & Cabling 系统与布线」。规则 P14–P17，规则版本 v1.4；备用线行用浅黄 #FFF3B0 标出。确认关（ConfirmPJ）新增：播放源位置、中控、同步组。
- 新常量：hdmiMax 15 m（已定）、spareRatio 10 %、powerMargin 10 %。
- **LED 异形屏**：ShapeLED.dc.html（第 2 步「屏形与输入」，先判屏形，再分面输入，含资料冲突表）、FacesLED.dc.html（第 3 步多面推荐，展开画布 + 按面表格 + S1–S7）。New Proposal 选 LED 后先进 ShapeLED；选「平面」回到原来的 Confirm.dc.html。示例：GMC U 形、Phoenix Sea Digital Cube L 形。
