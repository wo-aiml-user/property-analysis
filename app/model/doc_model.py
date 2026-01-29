"""
Pydantic models for Document operations.
"""

from pydantic import BaseModel
from typing import List, Optional


class ExtractedImage(BaseModel):
    """Model for an extracted image from PDF."""
    filename: str
    page: int
    caption: str = ""
    url: str  # S3 public URL
    mime_type: str = "image/png"


class PDFUploadResponse(BaseModel):
    """Response model for PDF upload."""
    total_files: int
    total_pages: int
    total_images: int
    images: List[ExtractedImage]
    message: str = "PDFs processed successfully"
