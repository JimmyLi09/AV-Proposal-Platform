"""原件存储：写一次，之后只读，永不覆盖。"""
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import BinaryIO

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def original_name(name: str) -> str:
    """上传的文件名去掉路径部分（浏览器可能带 Windows 路径）。"""
    return re.split(r"[\\/]", name or "")[-1].strip() or "file"


def safe_name(name: str) -> str:
    """能在 Windows 上落盘的文件名。"""
    name = _ILLEGAL.sub("_", original_name(name)).rstrip(" .") or "file"
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.upper() in _RESERVED:
        stem = "_" + stem
    stem = stem[: 150 - len(ext)]
    return f"{stem}.{ext}" if ext else stem


def save_original(root: Path, rel_path: str, src: BinaryIO) -> tuple[str, int]:
    """写入新文件并设为只读，返回 (sha256, 字节数)。目标已存在时报错，绝不覆盖。"""
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    out = open(path, "xb")  # x：文件已存在就失败
    digest, size = hashlib.sha256(), 0
    try:
        with out:
            while chunk := src.read(1 << 20):
                digest.update(chunk)
                out.write(chunk)
                size += len(chunk)
    except BaseException:
        path.unlink()
        raise
    os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return digest.hexdigest(), size
