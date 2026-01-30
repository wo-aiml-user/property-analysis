"""
Pydantic models for Document operations.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class ExtractedImage(BaseModel):
    """Model for an extracted image from PDF."""
    filename: str
    page: int
    caption: str = ""
    url: str  # S3 public URL
    mime_type: str = "image/png"

class PDFUploadResponse(BaseModel):
    """Response model for PDF upload."""
    property_id: str
    total_files: int
    total_pages: int
    total_images: int
    images: List[ExtractedImage]
    pdf_urls: List[str] = []
    message: str = "PDFs processed successfully"

class PropertyData(BaseModel):
    """Model for storing property/session data in MongoDB."""
    property_id: str
    user_id: str
    files: List[ExtractedImage]
    pdf_urls: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    chat_history: List[Dict[str, Any]] = [] # To store user's chat messages

class ProjectSummary(BaseModel):
    """Summary of a property project for the portfolio list."""
    property_id: str
    created_at: datetime
    total_images: int
    thumbnail_url: Optional[str] = None
