"""数据对象（方案「数据对象、Rev 锁定与状态流转」）。第 1 步只建项目、原件、Proposal 与 Rev 骨架。"""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    # SQLite 不存时区，一律存 UTC
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    """轻账号：只选名字，无密码无权限；用来记录谁做了什么。"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    role: Mapped[str] = mapped_column(String(40), default="")  # Sales / PM / 工程，只是标签
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    client: Mapped[str] = mapped_column(String(200))
    project_no: Mapped[str | None] = mapped_column(String(40))  # Project Platform 编号，可后补
    location: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    owner: Mapped[User] = relationship(foreign_keys=[owner_id])
    files: Mapped[list["SourceFile"]] = relationship(order_by="SourceFile.id")
    proposals: Mapped[list["Proposal"]] = relationship(order_by="Proposal.id")


class SourceFile(Base):
    """原件：只读，永不覆盖。没有任何修改或删除的接口。"""
    __tablename__ = "source_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    filename: Mapped[str] = mapped_column(String(255))  # 上传时的原文件名
    file_type: Mapped[str] = mapped_column(String(20))  # 扩展名，如 pdf / xlsx / jpg
    grade: Mapped[str | None] = mapped_column(String(1))  # A / B / C，读取文件时（第 4 步）判定
    stored_path: Mapped[str] = mapped_column(String(500), unique=True)  # 相对资料目录
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int]
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)
    # 第 4 步：服务器读取结果（读取方式见 app/extract/run.py）
    read_status: Mapped[str | None] = mapped_column(String(10))  # reading / read / attached / failed
    read_method: Mapped[str | None] = mapped_column(String(20))
    read_note: Mapped[str | None] = mapped_column(Text)
    read_text: Mapped[str | None] = mapped_column(Text)  # 读到的文字（前 2000 字），供核对
    read_at: Mapped[datetime | None]

    uploader: Mapped[User] = relationship()
    extracted: Mapped[list["ExtractedField"]] = relationship(order_by="ExtractedField.id", back_populates="source_file")


class ExtractedField(Base):
    """从文件里认出的字段（候选值）。重新读取时整份替换；方案里采用的值另存在 Rev 上。"""
    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    field: Mapped[str] = mapped_column(String(40))
    value: Mapped[object] = mapped_column(JSON)
    confidence: Mapped[str] = mapped_column(String(6))  # high / medium / low
    page: Mapped[int | None]
    location: Mapped[str] = mapped_column(String(120), default="")  # p.2、LED!B6、图层 · 坐标
    snippet: Mapped[str] = mapped_column(Text, default="")  # 原文
    crop_path: Mapped[str | None] = mapped_column(String(300))  # 原文截图（副本），相对资料目录

    source_file: Mapped[SourceFile] = relationship(back_populates="extracted")


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(200))  # 如 LED-1 Lobby、PJ-1 展厅投影墙
    business_line: Mapped[str] = mapped_column(String(10))  # LED / PJ
    mode: Mapped[str] = mapped_column(String(1), default="A")  # 档位：V1 只有 A Light
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    revisions: Mapped[list["Revision"]] = relationship(order_by="Revision.rev_no")


class Revision(Base):
    __tablename__ = "revisions"
    __table_args__ = (UniqueConstraint("proposal_id", "rev_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"))
    rev_no: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), default="draft")
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None]
    # 批准时锁定的 6 样：确认后的输入、规则版本、产品库版本、Cost 快照、模板版本、生成文件
    locked: Mapped[dict | None] = mapped_column(JSON)
    inputs: Mapped[dict | None] = mapped_column(JSON)  # 已确认输入（第 3 步先手工录入）
    cabinet_id: Mapped[str | None] = mapped_column(String(40))  # 换型号：选了推荐以外的箱体
    manual_lines: Mapped[list | None] = mapped_column(JSON)  # BOQ 人工增加的行（带单价，标「手工」）
    sell_price_cents: Mapped[int | None]  # 售价人工填写，可空
    price_display: Mapped[str | None] = mapped_column(String(10))  # PDF 里的价格：none / total / itemised
    # 每个输入的来源与确认：{字段: {source: manual|file, confidence, filename, location, snippet,
    #                              extracted_id, confirmed_by, confirmed_at}}
    input_meta: Mapped[dict | None] = mapped_column(JSON)

    author: Mapped[User] = relationship(foreign_keys=[author_id])


class RuleSetVersion(Base):
    """规则集版本：每次保存整套另存一个新版本，旧版本永不修改；Rev 锁定的就是这个版本。"""
    __tablename__ = "rule_set_versions"
    __table_args__ = (UniqueConstraint("business_line", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    business_line: Mapped[str] = mapped_column(String(10))
    version: Mapped[str] = mapped_column(String(20))  # v1.3、v1.4 …
    content: Mapped[dict] = mapped_column(JSON)  # 输入定义、参数、规则算式
    reason: Mapped[str] = mapped_column(Text, default="")  # 修改原因
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # 初始版本为空
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    author: Mapped[User | None] = relationship()


class ProductLibraryVersion(Base):
    """产品库版本：每次保存整库另存一个新版本，旧版本永不修改。"""
    __tablename__ = "product_library_versions"
    __table_args__ = (UniqueConstraint("business_line", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    business_line: Mapped[str] = mapped_column(String(10))
    version: Mapped[str] = mapped_column(String(20))  # v1.0、v1.1 …
    content: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    author: Mapped[User | None] = relationship()


class CostEntry(Base):
    """单价：人工录入，只追加不修改，同一个 key 以最新一条为准。"""
    __tablename__ = "cost_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), index=True)  # 产品编号（加尺寸）或通用项，如 IC-25:640x480、data_cable
    amount_cents: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3), default="SGD")
    valid_until: Mapped[date | None]
    note: Mapped[str] = mapped_column(Text, default="")
    sample: Mapped[bool] = mapped_column(default=False)
    entered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    entered_at: Mapped[datetime] = mapped_column(default=utcnow)

    author: Mapped[User | None] = relationship()
