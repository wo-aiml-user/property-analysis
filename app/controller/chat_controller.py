"""
Chat Controller - Image regeneration endpoint.
"""

from fastapi import APIRouter, Depends, Request
from loguru import logger
from datetime import datetime
from app.model.doc_model import PropertyData

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
    Accept image IDs and user feedback, lookup S3 URLs, regenerate images using OpenAI.
    
    Flow:
    1. Frontend sends image IDs (not URLs)
    2. Backend looks up image IDs in MongoDB to get S3 URLs
    3. Downloads images from S3 (URL -> bytes)
    4. Sends to OpenAI model for regeneration
    5. Uploads regenerated images to S3
    6. Returns new S3 URLs
    
    Parameters:
    - image_ids: List of image IDs to regenerate
    - user_feedback: User's preferences for how to regenerate the images
    
    Returns:
    - regenerated_images: Array of {url, mime_type}
    - description: Text description from the model
    - input_count: Number of input images processed
    """
    if not request_body.image_ids:
        return error_response("At least one image ID is required", 400)
    
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
    
    # 2. Lookup image IDs to get S3 URLs
    property_data = PropertyData(**property_doc)
    
    # Create a mapping of image ID -> S3 URL
    image_map = {img.id: img.url for img in property_data.files}
    
    # Get S3 URLs for requested image IDs
    image_urls = []
    for img_id in request_body.image_ids:
        if img_id not in image_map:
            logger.warning(f"Image ID {img_id} not found in property {property_id}")
            continue
        image_urls.append(image_map[img_id])
    
    if not image_urls:
        return error_response("No valid images found for the provided IDs", 400)
    
    try:
        # Use OpenAI Client
        client = get_openai_client()
        
        # Prepare image data with URLs
        images_data = [
            {"url": url, "mime_type": "image/png"}
            for url in image_urls
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
            input_count=result.get("input_count", len(image_urls)),
            message=f"Successfully regenerated {len(regenerated)} image(s)"
        )
        
        # Save Chat History (Async)
        chat_entry = {
            "timestamp": datetime.utcnow(),
            "role": "user",
            "content": request_body.user_feedback,
            "image_ids": request_body.image_ids  # Store IDs instead of URLs
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
