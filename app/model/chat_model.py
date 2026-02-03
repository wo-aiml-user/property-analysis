"""
Pydantic models for Chat/Image Regeneration operations.
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class ImageInput(BaseModel):
    """Single image input for chat."""
    url: Optional[str] = None  # S3 Object URL (preferred from frontend)
    s3_key: Optional[str] = None  # Direct S3 key (alternative)
    data: Optional[str] = None  # Base64 encoded image data (fallback)
    mime_type: str = "image/png"


class ChatRequest(BaseModel):
    """Request model for image regeneration chat."""
    property_id: str = Field(..., description="ID of the property being edited")
    image_ids: List[str] = Field(..., description="List of image IDs to regenerate")
    user_feedback: str = Field(..., description="User's regeneration preferences and feedback")


class RegeneratedImage(BaseModel):
    """A regenerated image from the LLM."""
    url: str  # S3 Object URL
    mime_type: str = "image/png"


class ChatResponse(BaseModel):
    """Response model for image regeneration."""
    regenerated_images: List[RegeneratedImage] = Field(default_factory=list)
    description: str = ""
    input_count: int = 0
    message: str = "Images regenerated successfully"
