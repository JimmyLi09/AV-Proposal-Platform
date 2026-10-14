"""规则集和产品库共用的版本做法：每次保存整份另存新版本，旧版本永不修改。"""
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import iso


def latest(db: Session, model, line: str):
    row = db.scalars(select(model).where(model.business_line == line).order_by(model.id.desc())).first()
    if row is None:
        raise HTTPException(404, "没有这条业务线")
    return row


def history(db: Session, model, line: str) -> list:
    return list(db.scalars(select(model).where(model.business_line == line).order_by(model.id.desc())))


def next_label(label: str) -> str:
    major, minor = map(int, re.fullmatch(r"v(\d+)\.(\d+)", label).groups())
    return f"v{major}.{minor + 1}"


def check_base(base, base_id: int, content: dict) -> None:
    if base_id != base.id:
        raise HTTPException(409, f"已经更新到 {base.version}，请刷新后再改")
    if content == base.content:
        raise HTTPException(422, "没有修改")


def version_out(v, content: bool = True) -> dict:
    out = {"id": v.id, "business_line": v.business_line, "version": v.version, "reason": v.reason,
           "created_by": v.author.name if v.author else None, "created_at": iso(v.created_at)}
    return out | {"content": v.content} if content else out
