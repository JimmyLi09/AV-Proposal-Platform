"""上传后在后台读取文件（提取中），读完把结果写回数据库。"""
from ..models import ExtractedField, SourceFile, utcnow
from .run import extract


def read_files(state, file_ids: list[int]) -> None:
    for fid in file_ids:
        with state.Session() as db:
            f = db.get(SourceFile, fid)
            if f is None:
                continue
            try:
                r = extract(state.data_dir / f.stored_path, f.file_type, state.data_dir, f"derived/{f.id}", state.oda)
            except Exception as e:  # 兜底：任何意外都不能让文件一直停在「读取中」
                r = {"grade": "C", "status": "failed", "method": "none", "note": f"读取失败：{type(e).__name__}",
                     "fields": [], "text": ""}
            for old in f.extracted:
                db.delete(old)
            for x in r["fields"]:
                db.add(ExtractedField(source_file_id=f.id, field=x["field"], value=x["value"], page=x["page"],
                                      confidence=x["confidence"], location=x["location"], snippet=x["snippet"],
                                      crop_path=x["crop"]))
            f.grade, f.read_status, f.read_method = r["grade"], r["status"], r["method"]
            f.read_note, f.read_text, f.read_at = r["note"], r["text"], utcnow()
            db.commit()
