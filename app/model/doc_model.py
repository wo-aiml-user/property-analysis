"""
Pydantic models for Document operations.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

from enum import Enum

class ImageCategory(str, Enum):
    EXTERIOR = "exterior"
    KITCHEN = "kitchen"
    LIVING_ROOM = "living_room"
    DINING_ROOM = "dining_room"
    BEDROOM = "bedroom"
    BATHROOM = "bathroom"
    INTERIOR = "interior" # General interior
    OTHER = "other"
    UNCATEGORIZED = "uncategorized"

class ExtractedImage(BaseModel):
    """Model for an extracted image from PDF."""
    id: str = ""  
    filename: str
    page: int
    caption: str = ""
    url: str  
    mime_type: str = "image/png"
    category: str = "uncategorized"  # Frontend handles categorization

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
    files: List[ExtractedImage] # Storing all in one list for simplicity in DB, will filter in API
    pdf_urls: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    chat_history: List[Dict[str, Any]] = []

class ProjectSummary(BaseModel):
    """Summary of a property project for the portfolio list."""
    property_id: str
    created_at: datetime
    total_images: int
    thumbnail_url: Optional[str] = None

class ExtractedImageResponse(BaseModel):
    """Response model for extracted image (excludes S3 URL)."""
    id: str
    filename: str
    page: int
    caption: str = ""
    mime_type: str = "image/png"

class PropertyDataResponse(BaseModel):
    """Response model for property data (excludes S3 URLs from images)."""
    property_id: str
    user_id: str
    files: List[ExtractedImageResponse]
    pdf_urls: List[str] = []
    created_at: datetime
    chat_history: List[Dict[str, Any]] = []
