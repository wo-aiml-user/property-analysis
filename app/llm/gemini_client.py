"""
Gemini API Client for Image Regeneration.
Uses the new google.genai package for image generation.
Downloads images from S3 using keys.
"""

from google import genai
from google.genai import types
from PIL import Image
from typing import Optional, Dict, Any, List
import base64
import io
from loguru import logger
from app.config import settings
from app.llm.prompts import image_regeneration_prompt
from app.services.s3_service import get_s3_service


class GeminiClient:
    """Wrapper for Google Gemini API with image generation."""
    
    def __init__(self):
        """Initialize Gemini client with API key."""
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not configured in settings")
        
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model = settings.GEMINI_MODEL
        self.s3_service = get_s3_service()
        logger.info(f"Gemini client initialized with model: {self.model}")
    
    def _base64_to_pil_image(self, base64_data: str) -> Image.Image:
        """Convert base64 string to PIL Image."""
        if "," in base64_data:
            base64_data = base64_data.split(",")[1]
        image_bytes = base64.standard_b64decode(base64_data)
        return Image.open(io.BytesIO(image_bytes))
    
    def _extract_s3_key_from_url(self, url: str) -> Optional[str]:
        """Extract S3 key from Object URL."""
        # URL format: https://bucket.s3.region.amazonaws.com/key
        try:
            if ".amazonaws.com/" in url:
                key = url.split(".amazonaws.com/")[1]
                # Remove query params if any
                if "?" in key:
                    key = key.split("?")[0]
                return key
        except Exception as e:
            logger.warning(f"Could not extract S3 key from URL: {e}")
        return None
    
    def _url_to_pil_image(self, url: str) -> Optional[Image.Image]:
        """Download image from S3 URL and convert to PIL Image."""
        s3_key = self._extract_s3_key_from_url(url)
        if s3_key:
            image_bytes = self.s3_service.get_s3_file_buffer(s3_key)
            if image_bytes:
                return Image.open(io.BytesIO(image_bytes))
        return None
    
    def _s3_key_to_pil_image(self, s3_key: str) -> Optional[Image.Image]:
        """Download image from S3 by key and convert to PIL Image."""
        image_bytes = self.s3_service.get_s3_file_buffer(s3_key)
        if image_bytes:
            return Image.open(io.BytesIO(image_bytes))
        return None
    
    def _pil_image_to_base64(self, image: Image.Image, format: str = "PNG") -> str:
        """Convert PIL Image to base64 string."""
        buffer = io.BytesIO()
        image.save(buffer, format=format)
        buffer.seek(0)
        return base64.standard_b64encode(buffer.read()).decode("utf-8")
    
    def _pil_image_to_bytes(self, image: Image.Image, format: str = "PNG") -> bytes:
        """Convert PIL Image to bytes."""
        buffer = io.BytesIO()
        image.save(buffer, format=format)
        buffer.seek(0)
        return buffer.read()
    
    async def regenerate_images(
        self,
        images: List[Dict[str, str]],
        user_feedback: str,
        upload_to_s3: bool = True
    ) -> Dict[str, Any]:
        """
        Regenerate images based on user feedback.
        
        Args:
            images: List of dicts with either:
                    - 's3_key' (S3 object key)
                    - 'url' (S3 Object URL - from frontend)
                    - 's3_key' (S3 object key)
                    - 'data' (base64 encoded image)
            user_feedback: User's renovation/regeneration preferences
            upload_to_s3: Whether to upload generated images to S3
            
        Returns:
            Dict with regenerated images (S3 URLs if uploaded, base64 otherwise)
        """
        try:
            prompt = image_regeneration_prompt.format(user_feedback=user_feedback)
            contents = [prompt]
            
            for img in images:
                pil_image = None
                
                # Priority: URL -> s3_key -> base64
                # Check if URL provided
                if "url" in img and img["url"]:
                    pil_image = self._url_to_pil_image(img["url"])
                # Check if S3 key provided
                elif "s3_key" in img and img["s3_key"]:
                    pil_image = self._s3_key_to_pil_image(img["s3_key"])
                # Check data field - could be base64 or mistakenly a URL
                elif "data" in img and img["data"]:
                    data = img["data"]
                    # Check if data is actually a URL (common mistake)
                    if data.startswith("http://") or data.startswith("https://"):
                        pil_image = self._url_to_pil_image(data)
                    else:
                        try:
                            pil_image = self._base64_to_pil_image(data)
                        except Exception as e:
                            logger.warning(f"Failed to decode base64: {e}")
                
                if pil_image:
                    contents.append(pil_image)
                else:
                    logger.warning(f"Could not load image: {img.get('url', img.get('s3_key', 'unknown'))}")
            
            if len(contents) == 1:
                return {
                    "error": "No valid images could be loaded",
                    "regenerated_images": [],
                    "description": ""
                }
            
            # Generate with image output
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"]
                )
            )
            
            # Extract generated images
            generated_images = []
            text_response = ""
            
            for part in response.parts:
                if part.text is not None:
                    text_response += part.text
                elif part.inline_data is not None:
                    # Get image bytes directly from inline_data
                    image_bytes = part.inline_data.data
                    mime_type = part.inline_data.mime_type or "image/png"
                    
                    if upload_to_s3:
                        s3_result = self.s3_service.upload_image(
                            image_bytes=image_bytes,
                            folder="regenerated",
                            filename="regen",
                            mime_type=mime_type
                        )
                        
                        if s3_result:
                            generated_images.append({
                                "url": s3_result["url"],
                                "mime_type": mime_type
                            })
                        else:
                            generated_images.append({
                                "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                                "mime_type": mime_type
                            })
                    else:
                        generated_images.append({
                            "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                            "mime_type": mime_type
                        })
            
            logger.info(f"Generated {len(generated_images)} images")
            
            return {
                "regenerated_images": generated_images,
                "description": text_response,
                "input_count": len(images)
            }
            
        except Exception as e:
            logger.error(f"Error regenerating images: {e}")
            return {
                "error": str(e),
                "regenerated_images": [],
                "description": "Failed to generate images"
            }


# Singleton instance
_gemini_client: Optional[GeminiClient] = None


def get_gemini_client() -> GeminiClient:
    """Get or create the Gemini client singleton."""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = GeminiClient()
    return _gemini_client
