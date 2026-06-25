import fitz  # PyMuPDF
import pdfplumber
import os
from typing import List, Dict, Any, Tuple
from pathlib import Path
from src.models.document import Document, DocumentMetadata
from src.utils.logger import logger

class PDFParser:
    def __init__(self, use_ocr: bool = False):
        self.use_ocr = use_ocr
        # Initialize OCR if needed (e.g., PaddleOCR)
        if self.use_ocr:
            try:
                from paddleocr import PaddleOCR
                self.ocr = PaddleOCR(use_angle_cls=True, lang="ch")
            except ImportError:
                logger.warning("PaddleOCR not installed, OCR functionality will be disabled.")
                self.use_ocr = False

    def parse(self, file_path: str) -> Document:
        """
        Parse a PDF file and return a Document object with content and metadata.
        Optimized for large documents by processing page by page.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            # 1. Extract Metadata using PyMuPDF
            doc = fitz.open(file_path)
            metadata = doc.metadata
            page_count = doc.page_count
            
            logger.info(f"Starting to parse PDF: {path.name} ({page_count} pages)")
            
            doc_metadata = DocumentMetadata(
                title=metadata.get("title", path.stem),
                author=metadata.get("author", ""),
                creation_date=metadata.get("creationDate", ""),
                page_count=page_count,
                source=str(path),
                file_type="pdf"
            )
            
            full_text_parts = []
            
            # 2. Extract Text
            # Try efficient extraction first (PyMuPDF)
            for page_num in range(page_count):
                if page_num % 10 == 0:
                    logger.info(f"Parsing page {page_num + 1}/{page_count} of {path.name}")
                
                page = doc[page_num]
                text = page.get_text()
                
                if text.strip():
                    full_text_parts.append(f"[Page {page_num + 1}] {text}")
                else:
                    # If no text, might be an image/scanned PDF -> Try PDFPlumber or OCR
                    page_text = self._extract_complex_page(file_path, page_num)
                    full_text_parts.append(f"[Page {page_num + 1}] {page_text}")
            
            doc.close()
            
            # Combine text using a more memory-efficient way for very large docs if needed
            # But for now, RAG usually needs the full content to chunk it.
            combined_text = "\n\n".join(full_text_parts)
            
            logger.info(f"Finished parsing PDF: {path.name}")
            
            return Document(
                filename=path.name,
                content=combined_text,
                metadata=doc_metadata,
                status="processed"
            )
            
        except Exception as e:
            logger.error(f"Error parsing PDF {file_path}: {str(e)}")
            return Document(
                filename=path.name,
                status="failed",
                error_message=str(e)
            )

    def _extract_complex_page(self, file_path: str, page_num: int) -> str:
        """
        Extract text from complex pages using PDFPlumber or OCR.
        """
        text = ""
        try:
            with pdfplumber.open(file_path) as pdf:
                page = pdf.pages[page_num]
                text = page.extract_text() or ""
                
                # If still empty and OCR is enabled, try OCR
                if not text.strip() and self.use_ocr:
                    # Convert page to image (requires converting pdfplumber page or using fitz to get image)
                    # For simplicity, let's assume we use fitz to get image for OCR
                    text = self._ocr_page(file_path, page_num)
        except Exception as e:
            logger.warning(f"Complex extraction failed for page {page_num}: {e}")
        
        return text

    def _ocr_page(self, file_path: str, page_num: int) -> str:
        """
        Perform OCR on a specific page.
        """
        import cv2
        import numpy as np
        
        doc = fitz.open(file_path)
        page = doc[page_num]
        pix = page.get_pixmap()
        img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        
        # Convert RGB to BGR for OpenCV/PaddleOCR if needed
        if pix.n == 3:
            img_data = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
            
        result = self.ocr.ocr(img_data, cls=True)
        txts = [line[1][0] for line in result[0]]
        return "\n".join(txts)
