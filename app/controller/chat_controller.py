"""
Chat Controller - Image regeneration endpoint.
"""

from fastapi import APIRouter, Depends, Request
from loguru import logger
from datetime import datetime

from app.utils.response import success_response, error_response
from app.model.chat_model import ChatRequest, ChatResponse, RegeneratedImage
from app.llm.openai_client import get_openai_client
from app.services.mongo_service import get_mongo_service, MongoService


router = APIRouter()


@router.post("/regenerate", response_model=ChatResponse)
async def regenerate_images(
    request_body: ChatRequest,
    request: Request,
    mongo: MongoService = Depends(get_mongo_service)
):
    """
    Accept image URLs (from /doc/upload) and user feedback, regenerate images using OpenAI.
    
    Flow:
    1. Frontend sends image URLs (from PDF extraction)
    2. Backend downloads images from S3 (URL -> bytes)
    3. Sends to OpenAI model for regeneration
    4. Uploads regenerated images to S3
    5. Returns new S3 URLs
    
    Parameters:
    - images: List of images with 'url' (S3 Object URL from /doc/upload)
    - user_feedback: User's preferences for how to regenerate the images
    
    Returns:
    - regenerated_images: Array of {url, mime_type}
    - description: Text description from the model
    - input_count: Number of input images processed
    """
    if not request_body.images:
        return error_response("At least one image is required", 400)
    
    if not request_body.user_feedback.strip():
        return error_response("User feedback is required", 400)

    # 1. Authentication & Ownership Check
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_id = request.state.jwt_payload.get("user_id")
    property_id = request_body.property_id
    
    # Check property ownership
    property_doc = await mongo.db["property_data"].find_one({
        "property_id": property_id,
        "user_id": user_id
    })
    
    if not property_doc:
        return error_response("Property not found or access denied", 404)
    
    # Filter valid images (must have url, s3_key, or data)
    valid_images = [img for img in request_body.images if img.url or img.s3_key or img.data]
    if not valid_images:
        return error_response("At least one image must have a URL or base64 data", 400)
    
    try:
        # Use OpenAI Client
        client = get_openai_client()
        
        # Prepare image data
        images_data = [
            {"url": img.url, "s3_key": img.s3_key, "data": img.data, "mime_type": img.mime_type}
            for img in valid_images
        ]
        

        result = await client.regenerate_images(
            images=images_data,
            user_feedback=request_body.user_feedback,
            upload_to_s3=True
        )
        
        if result.get("error"):
            return error_response(f"Image regeneration failed: {result['error']}", 500)
        
        # Build response with URLs
        regenerated = [
            RegeneratedImage(
                url=img.get("url", ""),
                mime_type=img.get("mime_type", "image/png")
            )
            for img in result.get("regenerated_images", [])
            if img.get("url")
        ]
        
        response = ChatResponse(
            regenerated_images=regenerated,
            description=result.get("description", ""),
            input_count=result.get("input_count", len(valid_images)),
            message=f"Successfully regenerated {len(regenerated)} image(s)"
        )
        
        # Save Chat History (Async)
        chat_entry = {
            "timestamp": datetime.utcnow(),
            "role": "user",
            "content": request_body.user_feedback
        }
        
        response_entry = {
            "timestamp": datetime.utcnow(),
            "role": "assistant",
            "images": [img.model_dump() for img in regenerated],
            "description": result.get("description", "")
        }
        
        await mongo.db["property_data"].update_one(
            {"property_id": property_id},
            {"$push": {"chat_history": {"$each": [chat_entry, response_entry]}}}
        )
        
        return success_response(response.model_dump(), 200)
        
    except Exception as e:
        logger.error(f"Error regenerating images: {e}")
        return error_response(f"Error regenerating images: {str(e)}", 500)
