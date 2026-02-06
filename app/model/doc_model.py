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
    url: str  
    mime_type: str = "image/png"
    category: str = "uncategorized"

class FileGroup(BaseModel):
    url: List[str] 
    images: List[ExtractedImage]
    total_images: int
    total_pages: int

class FilesStructure(BaseModel):
    mls: FileGroup = Field(default_factory=lambda: FileGroup(url=[], images=[], total_images=0, total_pages=0))
    comps: FileGroup = Field(default_factory=lambda: FileGroup(url=[], images=[], total_images=0, total_pages=0))

class PDFUploadResponse(BaseModel):
    """Response model for PDF upload."""
    property_id: str
    user_id: str
    total_files: int
    files: FilesStructure
    message: str = "PDFs processed successfully"

class PropertyFiles(BaseModel):
    """Categorized property files."""
    mls: FileGroup = Field(default_factory=lambda: FileGroup(url=[], images=[], total_images=0, total_pages=0))
    comps: FileGroup = Field(default_factory=lambda: FileGroup(url=[], images=[], total_images=0, total_pages=0))

class PropertyData(BaseModel):
    """Model for storing property/session data in MongoDB."""
    property_id: str
    user_id: str
    files: PropertyFiles = PropertyFiles()
    pdf_urls: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
    mime_type: str = "image/png"

class PropertyDataResponse(BaseModel):
    """Response model for property data (excludes S3 URLs from images)."""
    property_id: str
    user_id: str
    files: List[ExtractedImageResponse]
    pdf_urls: List[str] = []
    created_at: datetime
