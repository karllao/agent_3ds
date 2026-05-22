"""
文件操作工具函数。

提供异步文件保存、路径生成、文件清理等通用功能。
"""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path

import aiofiles
import aiofiles.os
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def save_upload_file(
    content: bytes,
    original_filename: str,
    sub_dir: Path,
    preserve_name: bool = False,
) -> Path:
    """
    将上传文件字节内容异步保存到指定目录。

    Args:
        content:           文件二进制内容。
        original_filename: 原始文件名（用于提取扩展名）。
        sub_dir:           目标子目录（如不存在会自动创建）。
        preserve_name:     True 时保留原始文件名；False 时使用 UUID 重命名。

    Returns:
        保存后文件的绝对路径。
    """
    # 确保目录存在
    sub_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(original_filename).suffix.lower()

    if preserve_name:
        # 同名文件覆盖
        filename = Path(original_filename).name
    else:
        # UUID + 日期前缀，避免冲突
        date_prefix = datetime.utcnow().strftime("%Y%m%d")
        unique_id = uuid.uuid4().hex[:12]
        filename = f"{date_prefix}_{unique_id}{suffix}"

    dest = sub_dir / filename

    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)

    logger.debug("File saved: path={} size={} bytes", dest, len(content))
    return dest


async def save_json_file(data: str, dest_path: Path) -> Path:
    """
    将 JSON 字符串异步写入文件。

    Args:
        data:      JSON 字符串。
        dest_path: 目标文件路径（会自动创建父目录）。

    Returns:
        写入后的文件路径。
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(dest_path, "w", encoding="utf-8") as f:
        await f.write(data)
    logger.debug("JSON file saved: path={}", dest_path)
    return dest_path


async def read_file_bytes(path: Path) -> bytes:
    """异步读取文件字节内容"""
    async with aiofiles.open(path, "rb") as f:
        return await f.read()


async def read_text_file(path: Path, encoding: str = "utf-8") -> str:
    """异步读取文本文件"""
    async with aiofiles.open(path, "r", encoding=encoding) as f:
        return await f.read()


async def remove_file(path: Path, missing_ok: bool = True) -> bool:
    """
    异步删除文件。

    Args:
        path:       文件路径。
        missing_ok: True 时文件不存在不抛异常。

    Returns:
        True 表示文件被删除，False 表示文件不存在。
    """
    try:
        await aiofiles.os.remove(path)
        logger.debug("File removed: {}", path)
        return True
    except FileNotFoundError:
        if missing_ok:
            return False
        raise


def compute_file_hash(content: bytes, algorithm: str = "sha256") -> str:
    """
    计算文件内容哈希（用于校验文件完整性或去重）。

    Args:
        content:   文件字节。
        algorithm: 哈希算法，默认 sha256。

    Returns:
        十六进制哈希字符串。
    """
    h = hashlib.new(algorithm)
    h.update(content)
    return h.hexdigest()


def get_mime_type(filename: str) -> str:
    """推断文件 MIME 类型"""
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def build_storage_path(
    base_dir: Path,
    project_id: int,
    category: str,
    filename: str,
) -> Path:
    """
    构建结构化存储路径。

    路径格式：{base_dir}/{category}/{project_id}/{filename}

    Args:
        base_dir:   存储根目录。
        project_id: 项目 ID。
        category:   文件分类（如 cad / json / max / preview）。
        filename:   文件名。

    Returns:
        完整目标路径（父目录已创建）。
    """
    dest = base_dir / category / str(project_id) / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


async def ensure_dir(path: Path) -> Path:
    """异步确保目录存在（不存在则创建）"""
    await aiofiles.os.makedirs(path, exist_ok=True)
    return path


def format_file_size(size_bytes: int) -> str:
    """将字节数格式化为人类可读字符串（KB / MB / GB）"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.2f} GB"
