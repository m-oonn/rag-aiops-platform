from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
import shutil
import os
import uuid
from pathlib import Path
from src.settings import settings
from src.services.pdf_processor import PDFProcessorService
from src.models.document import Document

router = APIRouter()
processor_service = PDFProcessorService()

@router.post("/upload", response_model=Document)
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Save file
    file_id = str(uuid.uuid4())
    filename = f"{file_id}_{file.filename}"
    file_path = settings.UPLOAD_DIR / filename
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {e}")

    # Initialize document object
    document = Document(
        id=file_id,
        filename=file.filename,
        status="processing"
    )

    # Process in background
    background_tasks.add_task(processor_service.process_file, str(file_path))
    
    return document
