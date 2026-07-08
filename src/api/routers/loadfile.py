from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Depends
import shutil
import os
import uuid
from pathlib import Path
from src.settings import settings
from src.services.pdf_processor import PDFProcessorService
from src.models.document import Document
from src.api.dependencies import get_current_user
from src.database.models import User

router = APIRouter()
processor_service = PDFProcessorService()

_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".csv", ".pptx", ".md", ".txt", ".html"}
_ALLOWED_MIME_TYPES = {  # 白名单,防恶意文件
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/markdown",
    "text/plain",
    "text/html",
    "application/octet-stream",  # fallback for some tooling
}


def _safe_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def _sanitize_filename(filename: str) -> str:
    """安全最佳实践: 净化文件名，移除路径穿越字符和危险字符。

    防止攻击者通过 file.filename 包含 ../.. 写入 UPLOAD_DIR 之外的位置。
    """
    import re
    # 移除路径分隔符和 ..
    safe = filename.replace("..", "").replace("/", "_").replace("\\", "_")
    # 移除控制字符
    safe = re.sub(r'[\x00-\x1f]', '', safe)
    # 限制长度
    if len(safe) > 255:
        name, ext = os.path.splitext(safe)
        safe = name[:255 - len(ext)] + ext
    return safe or "unnamed"


@router.post("/upload", response_model=Document)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    ext = _safe_extension(file.filename)
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    if file.content_type and file.content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file.content_type}")

    # 读取文件内容并校验大小
    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件超过最大限制 {_MAX_FILE_SIZE // (1024*1024)}MB")

    file_id = str(uuid.uuid4())
    # 安全最佳实践: 净化文件名后再拼接路径，防止路径穿越
    safe_filename = _sanitize_filename(file.filename)
    filename = f"{file_id}_{safe_filename}"
    file_path = settings.UPLOAD_DIR / filename

    try:
        with open(file_path, "wb") as buffer:
            buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")

    document = Document(
        id=file_id,
        filename=safe_filename,
        status="processing"
    )

    background_tasks.add_task(processor_service.process_file, str(file_path))

    return document
