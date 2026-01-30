"""
OpenAI API Client for Image Regeneration.
Uses the 'gpt-image-1.5' model as requested.
"""

from openai import OpenAI
from typing import Optional, Dict, Any, List
import base64
import io
from loguru import logger
from app.config import settings
from app.llm.prompts import IMAGE_REGENERATION_PROMPT
from app.services.s3_service import get_s3_service

class OpenAIClient:
    """Wrapper for OpenAI API with image generation/editing."""
    
    _instance: Optional['OpenAIClient'] = None
    
    def __init__(self):
        """Initialize OpenAI client with API key."""
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not configured in settings")
        
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        # Use specific model as requested
        self.model = settings.OPENAI_MODEL
        self.s3_service = get_s3_service()
        logger.info(f"OpenAI client initialized with model: {self.model}")
    
    def _extract_s3_key_from_url(self, url: str) -> Optional[str]:
        """Extract S3 key from Object URL."""
        try:
            if ".amazonaws.com/" in url:
                key = url.split(".amazonaws.com/")[1]
                if "?" in key:
                    key = key.split("?")[0]
                return key
        except Exception as e:
            logger.warning(f"Could not extract S3 key from URL: {e}")
        return None
    
    def _get_image_bytes(self, img_info: Dict[str, str]) -> Optional[bytes]:
        """Resolve image bytes from URL, s3_key, or base64 data."""
        # Priority: URL -> s3_key -> data
        if "url" in img_info and img_info["url"]:
            s3_key = self._extract_s3_key_from_url(img_info["url"])
            if s3_key:
                return self.s3_service.get_s3_file_buffer(s3_key)
                
        if "s3_key" in img_info and img_info["s3_key"]:
            return self.s3_service.get_s3_file_buffer(img_info["s3_key"])
            
        if "data" in img_info and img_info["data"]:
            try:
                data = img_info["data"]
                if "," in data:
                    data = data.split(",")[1]
                return base64.standard_b64decode(data)
            except Exception as e:
                logger.warning(f"Failed to decode base64: {e}")
                
        return None

    async def regenerate_images(
        self,
        images: List[Dict[str, str]],
        user_feedback: str,
        upload_to_s3: bool = True
    ) -> Dict[str, Any]:
        """
        Regenerate images based on user feedback using OpenAI.
        """
        try:
            prompt = IMAGE_REGENERATION_PROMPT.format(user_feedback=user_feedback)
            
            # Prepare images as file-like objects (BytesIO)
            image_files = []
            for img in images:
                img_bytes = self._get_image_bytes(img)
                if img_bytes:
                    # Provide a name attribute as some libs expect it
                    buf = io.BytesIO(img_bytes)
                    buf.name = "input_image.png" 
                    image_files.append(buf)
                else:
                    logger.warning(f"Could not load image: {img}")
            
            if not image_files:
                return {
                    "error": "No valid images could be loaded",
                    "regenerated_images": [],
                    "description": ""
                }
            
            logger.info(f"Sending {len(image_files)} images to OpenAI ({self.model})")
            
            # Call OpenAI API
            # NOTE: This usage matches the user's specific request for gpt-image-1.5 
            # accepting a list of images.
            response = self.client.images.edit(
                model=self.model,
                image=image_files, # List of file-like objects
                prompt=prompt
            )
            
            generated_images = []
            description = "Regenerated images based on feedback."
            
            # Process response
            # Assuming response structure based on standard OpenAI Image objects
            # response.data is a list of Image objects
            if hasattr(response, 'data'):
                for item in response.data:
                    # Item has b64_json or url
                    if hasattr(item, 'b64_json') and item.b64_json:
                        image_bytes = base64.b64decode(item.b64_json)
                        mime_type = "image/png"
                        
                        if upload_to_s3:
                            s3_result = self.s3_service.upload_image(
                                image_bytes=image_bytes,
                                folder="regenerated",
                                filename="openai_regen",
                                mime_type=mime_type
                            )
                            if s3_result:
                                generated_images.append({
                                    "url": s3_result["url"],
                                    "mime_type": mime_type
                                })
                            else:
                                 generated_images.append({
                                    "data": item.b64_json,
                                    "mime_type": mime_type
                                })
                        else:
                            generated_images.append({
                                "data": item.b64_json,
                                "mime_type": mime_type
                            })
                    elif hasattr(item, 'url') and item.url:
                         generated_images.append({
                            "url": item.url,
                            "mime_type": "image/png"
                        })
                        
            logger.info(f"OpenAI generated {len(generated_images)} images")
            
            return {
                "regenerated_images": generated_images,
                "description": description,
                "input_count": len(images)
            }
            
        except Exception as e:
            logger.error(f"Error regenerating images with OpenAI: {e}")
            return {
                "error": str(e),
                "regenerated_images": [],
                "description": "Failed to generate images"
            }
        finally:
            # Close file handles
            for f in image_files:
                f.close()

def get_openai_client() -> OpenAIClient:
    """Get OpenAI client singleton."""
    if OpenAIClient._instance is None:
        OpenAIClient._instance = OpenAIClient()
    return OpenAIClient._instance
