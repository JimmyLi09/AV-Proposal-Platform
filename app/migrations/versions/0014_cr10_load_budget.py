"""CR-10: load budget — F5 / F6 / F9 from spec-sheet data, new W1 wiring layout, cabinet max current / power

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-08 12:00:00
"""
import re

from alembic import op
import sqlalchemy as sa

from app.models import utcnow


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None

# 新参数（px_per_data_cable 改为 655,360 并移到「带载预算」组）。circuit_kw 不再用，从新版本里去掉；旧版本原样保留
PARAMS = [
    {"name": "mcb_a", "group": "Load budget 带载预算", "label": "MCB rating (single phase) 空开（单相）", "unit": "A", "value": 20, "status": "set", "source": "公司标准（Jimmy）"},
    {"name": "mains_v", "group": "Load budget 带载预算", "label": "Mains voltage 市电电压", "unit": "V", "value": 230, "status": "set", "source": "新加坡市电"},
    {"name": "load_factor", "group": "Load budget 带载预算", "label": "Continuous load factor 持续负载系数", "unit": "", "value": 0.85, "status": "set", "source": "Jimmy：先用 0.85，可以参考以前的数据"},
    {"name": "power_cable_mm2", "group": "Load budget 带载预算", "label": "Power cable size 电源线线径", "unit": "mm²", "value": 2.5, "status": "set", "options": [1.5, 2.5, 4], "source": "Thailand P1.8 接线图（3 × 2.5 mm²）"},
    {"name": "chain_max", "group": "Load budget 带载预算", "label": "Max cabinets per power chain 每条电源线最多串接箱体", "unit": "个", "value": 10, "status": "set", "source": "Jimmy：按电源带载和箱体尺寸，最多 10–12 个，取 10"},
    {"name": "px_per_data_cable", "group": "Load budget 带载预算", "label": "Pixels per network port 每网口带载", "unit": "px", "value": 655360, "status": "set", "source": "厂家标称 655,360 = 1024 × 640（Absen 资料）；按公式 1000 Mbps × 93.6% ÷ 60 Hz ÷ 24 bit ≈ 650,000，MCTRL700 规格书约 650,000"},
    {"name": "data_grouping", "group": "Load budget 带载预算", "label": "Data grouping 网线分组", "unit": "", "value": "rows", "status": "review", "options": ["rows", "count"], "source": "默认按行整行（公司接线图做法，Thailand P1.8）；待 Jimmy 确认"},
    {"name": "ampacity_1_5_mm2", "group": "Cable ampacity 线径载流", "label": "Ampacity 1.5 mm² 1.5 mm² 载流", "unit": "A", "value": 16, "status": "sample", "source": "示例值，待公司用线的实际载流量"},
    {"name": "ampacity_2_5_mm2", "group": "Cable ampacity 线径载流", "label": "Ampacity 2.5 mm² 2.5 mm² 载流", "unit": "A", "value": 20, "status": "sample", "source": "示例值，待公司用线的实际载流量"},
    {"name": "ampacity_4_mm2", "group": "Cable ampacity 线径载流", "label": "Ampacity 4 mm² 4 mm² 载流", "unit": "A", "value": 27, "status": "sample", "source": "示例值，待公司用线的实际载流量"},
    {"name": "wiring_orientation", "group": "Wiring 接线", "label": "Wiring direction 接线方向", "unit": "", "value": "row", "status": "set", "options": ["row", "col"], "source": "公司接线图按行（Thailand P1.8）"},
    {"name": "power_route", "group": "Wiring 接线", "label": "Power routing 电源走线", "unit": "", "value": "S", "status": "set", "options": ["S", "straight"]},
    {"name": "data_route", "group": "Wiring 接线", "label": "Data routing 网线走线", "unit": "", "value": "straight", "status": "set", "options": ["S", "straight"]},
]
RULES = {
    "F5": {"id": "F5", "title": "Power 功率", "note": "Σ（各尺寸箱体数 × 每箱最大功率）÷ 1000，箱体数来自 F3、每箱最大功率来自产品库；产品没有每箱最大功率时，退回按面积 × 每平米功耗。", "outputs": [{"name": "power_kw", "unit": "kW", "decimals": 2, "cases": [{"when": "cabinets_w > 0", "expr": "cabinets_w / 1000"}, {"when": "environment == 'indoor'", "expr": "area_m2 * w_per_m2_indoor / 1000"}, {"when": "environment == 'outdoor'", "expr": "area_m2 * w_per_m2_outdoor / 1000"}, {"when": "environment == 'rental'", "expr": "area_m2 * w_per_m2_rental / 1000"}]}]},
    "F6": {"id": "F6", "title": "Power circuits 电源回路", "note": "每回路额定电流取空开和线径载流的小者，乘持续负载系数得可用电流；按最大单箱电流算每回路能带几箱（带载），再按每条电源线最多串接几箱（串接），两者取大。", "display": "{circuits}（带载 {circuits_by_load} / 串接 {circuits_by_chain}，取大）", "outputs": [{"name": "rated_a", "unit": "A", "cases": [{"when": "power_cable_mm2 == 1.5", "expr": "min(mcb_a, ampacity_1_5_mm2)"}, {"when": "power_cable_mm2 == 4", "expr": "min(mcb_a, ampacity_4_mm2)"}, {"expr": "min(mcb_a, ampacity_2_5_mm2)"}]}, {"name": "usable_a", "unit": "A", "decimals": 2, "cases": [{"expr": "rated_a * load_factor"}]}, {"name": "usable_kw", "unit": "kW", "decimals": 2, "cases": [{"expr": "usable_a * mains_v / 1000"}]}, {"name": "cab_per_circuit", "unit": "个", "cases": [{"expr": "floor(usable_a / cabinet_max_a)"}]}, {"name": "circuits_by_load", "unit": "路", "cases": [{"expr": "ceil(cabinets / cab_per_circuit)"}]}, {"name": "circuits_by_chain", "unit": "路", "cases": [{"expr": "ceil(cabinets / chain_max)"}]}, {"name": "circuits", "unit": "路", "cases": [{"expr": "max(circuits_by_load, circuits_by_chain)"}]}]},
    "W1": {"id": "W1", "title": "Wiring layout 接线布置", "note": "电源从最下一行靠配电箱一侧开始，按走线顺序把箱体连续平均分成 F6 的回路数；网线从最上一行靠发送卡一侧开始，按行整行或按箱数装。逐组检查电流、串接箱数和像素。", "step": "wiring_layout"},
    "F9": {"id": "F9", "title": "Data cables 数据线", "note": "按箱数最少要 ⌈总像素 ÷ 每网口带载⌉ 路；按行整行时用 W1 从上往下装整行的路数。再加备用。", "outputs": [{"name": "data_runs_count", "unit": "路", "cases": [{"expr": "ceil(total_pixels / px_per_data_cable)"}]}, {"name": "data_runs", "unit": "路", "cases": [{"when": "data_grouping == 'rows'", "expr": "wiring_data_runs"}, {"expr": "data_runs_count"}]}, {"name": "data_cables", "unit": "根", "cases": [{"expr": "data_runs + spare_data_cables"}]}]},
}
# 箱体每种尺寸的最大电流 / 功率：IC-25 是规格书真实值（P2.5 室内 640×480 / 640×640），其它示例箱体先填示例值
CABINET_MAX = {
    "IC-25": {"640x480": {"a": 0.96, "w": 120, "sample": False}, "640x640": {"a": 0.96, "w": 200, "sample": False}},
    "IC-19": {"640x480": {"a": 0.96, "w": 120, "sample": True}, "640x640": {"a": 0.96, "w": 200, "sample": True}},
    "OF-40": {"960x960": {"a": 3.2, "w": 740, "sample": True}},
}


def _table(name):
    return sa.table(name, sa.column('id', sa.Integer), sa.column('business_line', sa.String),
                    sa.column('version', sa.String), sa.column('content', sa.JSON), sa.column('reason', sa.Text),
                    sa.column('created_by', sa.Integer), sa.column('created_at', sa.DateTime))


def _next(version: str) -> str:
    major, minor = map(int, re.fullmatch(r"v(\d+)\.(\d+)", version).groups())
    return f"v{major}.{minor + 1}"


def upgrade() -> None:
    conn = op.get_bind()
    # 规则集：在最新的 LED 版本上另存一个新版本，其它规则和参数（包括用户改过的）不变
    sets = _table('rule_set_versions')
    last = conn.execute(sa.select(sets).where(sets.c.business_line == "LED").order_by(sets.c.id.desc())).first()
    if last is not None and not any(p["name"] == "mcb_a" for p in last.content["params"]):
        names = {p["name"] for p in PARAMS}
        params = [p for p in last.content["params"] if p["name"] not in names | {"circuit_kw"}]
        at = next((i + 1 for i, p in enumerate(params) if p["name"] == "circuits_per_db_box"), len(params))
        rules = [RULES.get(r["id"], r) for r in last.content["rules"] if r["id"] != "W1"]
        at_f9 = next((i for i, r in enumerate(rules) if r["id"] == "F9"), len(rules))
        content = dict(last.content, params=params[:at] + PARAMS + params[at:], rules=rules[:at_f9] + [RULES["W1"]] + rules[at_f9:])
        conn.execute(sets.insert().values(business_line="LED", version=_next(last.version), content=content,
                                          reason="CR-10：带载预算（空开 20 A、负载系数、线径、串接上限、每网口 655,360 px）和 W1 接线布置"
                                                 "（升级时自动生成）",
                                          created_by=None, created_at=utcnow()))
    # 产品库：示例箱体加上每种尺寸的最大电流 / 功率（已经有的不改）
    libs = _table('product_library_versions')
    last = conn.execute(sa.select(libs).where(libs.c.business_line == "LED").order_by(libs.c.id.desc())).first()
    if last is not None:
        products = [dict(p, cabinet_max=CABINET_MAX[p["id"]]) if p.get("category") == "cabinet" and p["id"] in CABINET_MAX
                    and not p.get("cabinet_max") else p for p in last.content["products"]]
        if products != last.content["products"]:
            conn.execute(libs.insert().values(business_line="LED", version=_next(last.version),
                                              content=dict(last.content, products=products),
                                              reason="CR-10：箱体加每箱最大电流 / 功率（IC-25 按规格书，其它为示例值；升级时自动生成）",
                                              created_by=None, created_at=utcnow()))


def downgrade() -> None:
    pass
