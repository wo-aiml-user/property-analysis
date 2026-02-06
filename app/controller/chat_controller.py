"""
Chat Controller - Image regeneration endpoint.
"""

from fastapi import APIRouter, Depends, Request, Body
from loguru import logger
from datetime import datetime
from app.model.doc_model import PropertyData
from app.model.chat_model import ChatMessage
from app.utils.response import success_response, error_response
from app.model.chat_model import ChatRequest, ChatResponse, RegeneratedImage, ChatHistory
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
    
    logger.info(f"Regeneration request from user {user_id} for property {property_id}")
    logger.debug(f"Input Image IDs: {request_body.image_ids}")
    logger.debug(f"User Feedback: {request_body.user_feedback}")

    # Check property ownership
    property_col = await mongo.get_property_data_collection()
    
    property_doc = await property_col.find_one({
        "property_id": property_id,
        "user_id": user_id
    })
    
    if not property_doc:
        return error_response("Property not found or access denied", 404)
    
    # 2. Lookup image IDs to get S3 URLs
    # property_data = PropertyData(**property_doc) # Skip Pydantic processing to handle legacy/mixed data
    
    files_data = property_doc.get("files", {})
    all_files = []
    
    if isinstance(files_data, list):
        all_files = files_data
    else:
        # Flatten nested structure safely
        mls_data = files_data.get("mls", {})
        if isinstance(mls_data, dict):
            all_files.extend(mls_data.get("images", []))
        elif isinstance(mls_data, list):
            all_files.extend(mls_data)
            
        comps_data = files_data.get("comps", {})
        if isinstance(comps_data, dict):
            all_files.extend(comps_data.get("images", []))
        elif isinstance(comps_data, list):
            all_files.extend(comps_data)
    
    # Create a mapping of image ID -> S3 URL
    # Note: Accessing dict keys since we rely on raw mongo doc
    image_map = {img.get("id"): img.get("url") for img in all_files if img.get("id")}
    
    # Get S3 URLs for requested image IDs
    image_urls = []
    for img_id in request_body.image_ids:
        if img_id not in image_map:
            logger.warning(f"Image ID {img_id} not found in property {property_id}")
            continue
        image_urls.append(image_map[img_id])
    
    if not image_urls:
        logger.warning(f"Regeneration failed: No valid image URLs found for IDs {request_body.image_ids}")
        return error_response("No valid images found for the provided IDs", 400)
    
    logger.info(f"Found {len(image_urls)} source images. Sending to OpenAI...")
    
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

        chat_entry = ChatMessage(
            role="user",
            content=request_body.user_feedback,
            image_ids=request_body.image_ids
        )
        
        response_entry = ChatMessage(
            role="assistant",
            images=regenerated,
            description=result.get("description", "")
        )
        
        chat_col = await mongo.get_chat_collection()
        
        # Update shared chat history document for this property
        await chat_col.update_one(
             {"property_id": property_id},
             {"$push": {"messages": {"$each": [chat_entry.model_dump(), response_entry.model_dump()]}}},
             upsert=True
        )
        
        logger.info(f"Regeneration completed and history saved. Returning {len(regenerated)} new images.")
        return success_response(response.model_dump(), 200)
        
    except Exception as e:
        logger.error(f"Error regenerating images: {e}")
        return error_response(f"Error regenerating images: {str(e)}", 500)

@router.get("/history", response_model=ChatHistory)
async def get_chat_history(
    request: Request,
    property_id: str = Body(..., embed=True),
    mongo: MongoService = Depends(get_mongo_service)
):
    """
    Get chat history for a specific property.
    """
    # 1. Authentication Check
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        logger.warning("Get chat history failed: No auth token")
        return error_response("Authentication required", 401)
        
    logger.info(f"Fetching chat history for property: {property_id}")

    try:
        chat_col = await mongo.get_chat_collection()
        chat_doc = await chat_col.find_one({"property_id": property_id})
        
        if not chat_doc:
            # Return empty history if not found
            logger.info(f"No chat history found for property {property_id}")
            return ChatHistory(property_id=property_id, messages=[])
            
        logger.info(f"Found chat history with {len(chat_doc.get('messages', []))} messages")
        return ChatHistory(**chat_doc)
        
    except Exception as e:
        logger.error(f"Error fetching chat history: {e}")
        return error_response("Failed to fetch chat history", 500)
