"""
Document Controller - PDF upload, image extraction, and property management.
"""

from pathlib import Path
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, Depends, Request, HTTPException, Body
from loguru import logger
from starlette.concurrency import run_in_threadpool
import uuid
from app.utils.response import success_response, error_response
from app.model.doc_model import (
    PDFUploadResponse, ExtractedImage, PropertyData, ProjectSummary,
    ImageCategory, PropertyDataResponse, ExtractedImageResponse
)
from app.services.pdf_extractor import get_pdf_extractor, PDFExtractor
from app.services.s3_service import get_s3_service, S3Service
from app.services.mongo_service import get_mongo_service, MongoService

router = APIRouter()

@router.post("/upload", response_model=PDFUploadResponse)
async def upload_pdfs(
    request: Request,
    property_id: str = Form(...),
    mls_files: List[UploadFile] = File(None),
    comps_files: List[UploadFile] = File(None),
    mongo: MongoService = Depends(get_mongo_service),
    s3: S3Service = Depends(get_s3_service),
    pdf_extractor: PDFExtractor = Depends(get_pdf_extractor)
):
    """
    Upload MLS and/or Comps PDF files, extract images, and create/update a property session.
    """
    # 1. Authentication Check
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_id = request.state.jwt_payload.get("user_id")
    user_email = request.state.jwt_payload.get("email")
    
    if not user_id or not user_email:
        return error_response("Invalid user session", 401)

    # Validate files
    files_to_process = []
    if mls_files:
        files_to_process.extend([(f, "mls") for f in mls_files])
    if comps_files:
        files_to_process.extend([(f, "comps") for f in comps_files])
        
    logger.info(f"Received {len(files_to_process)} files for property {property_id}")
    
    for file, _ in files_to_process:
        if not file.filename:
            continue
        if not file.filename.lower().endswith('.pdf'):
            return error_response(f"Only PDF files are allowed. Got: {file.filename}", 400)
    
    new_mls_images = []
    new_comps_images = []
    mls_urls = []
    comps_urls = []
    
    mls_total_pages = 0
    comps_total_pages = 0
    total_files = 0
    
    try:
        for file, category in files_to_process:
            if not file.filename:
                continue
            filename = file.filename
            total_files += 1
            logger.info(f"Processing {category.upper()} PDF: {filename}")
            
            try:
                # Step 1: Read file content
                file_content = await file.read()
                
                # Step 2: Upload PDF to S3
                pdf_s3_result = await run_in_threadpool(
                    s3.upload_file_to_s3,
                    buffer=file_content,
                    key=f"pdfs/{property_id}/{category}/{filename}",
                    content_type="application/pdf"
                )
                
                if not pdf_s3_result:
                    logger.error(f"Failed to upload PDF to S3: {filename}")
                    continue
                
                # Get public URL
                pdf_url = s3.get_public_url(f"pdfs/{property_id}/{category}/{filename}")
                
                if category == "mls":
                    mls_urls.append(pdf_url)
                else:
                    comps_urls.append(pdf_url)
                
                # Step 3: Extract images
                extraction_result = await run_in_threadpool(
                    pdf_extractor.extract_images_from_bytes,
                    pdf_bytes=file_content,
                    pdf_filename=filename,
                    folder=f"extracted/{property_id}/{category}/{Path(filename).stem}"
                )
                
                if category == "mls":
                    mls_total_pages += extraction_result.get('total_pages', 0)
                else:
                    comps_total_pages += extraction_result.get('total_pages', 0)
                
                # Step 4: Build image models
                for img in extraction_result.get('images', []):
                    image_id = uuid.uuid4().hex
                    caption = img.get('caption', '').strip()
                    
                    # Set category from caption if available, else 'unknown'
                    img_category = caption if caption else "unknown"
                    
                    image_model = ExtractedImage(
                        id=image_id,
                        filename=f"{filename}_{img['filename']}",
                        page=img['page'],
                        url=img['url'],
                        mime_type=img.get('mime_type', 'image/png'),
                        category=img_category
                    )
                    
                    if category == "mls":
                        new_mls_images.append(image_model)
                    else:
                        new_comps_images.append(image_model)
                
            except Exception as e:
                logger.error(f"Error processing PDF {filename}: {e}")
                continue
            finally:
                await file.close()
        
        # Step 5: Persist Property Data in prop_property_data collection
        
        property_col = await mongo.get_property_data_collection()
        
        # Check if property exists
        existing_prop = await property_col.find_one({"property_id": property_id})
        
        # Prepare data for DB
        mls_data = {
            "url": mls_urls,
            "images": [img.model_dump() for img in new_mls_images],
            "total_images": len(new_mls_images),
            "total_pages": mls_total_pages
        }
        
        comps_data = {
            "url": comps_urls,
            "images": [img.model_dump() for img in new_comps_images],
            "total_images": len(new_comps_images),
            "total_pages": comps_total_pages
        }

        if existing_prop:
            # Check ownership (security)
            if existing_prop.get("user_id") != user_id: 
                 return error_response("Property ID exists but belongs to another user", 403)

            # Property exists, append new entries to nested structures
            # Note: Merging totals logic here is simple addition; ideally we'd need to re-calculate or just increment
            # For simplicity, we assume we are ADDING to existing strings/lists
            
            update_ops = {
                "$push": {
                    "files.mls.url": {"$each": mls_urls},
                    "files.mls.images": {"$each": [img.model_dump() for img in new_mls_images]},
                    "files.comps.url": {"$each": comps_urls},
                    "files.comps.images": {"$each": [img.model_dump() for img in new_comps_images]}
                },
                "$inc": {
                    "files.mls.total_images": len(new_mls_images),
                    "files.mls.total_pages": mls_total_pages,
                    "files.comps.total_images": len(new_comps_images),
                    "files.comps.total_pages": comps_total_pages
                }
            }

            result = await property_col.update_one(
                {"property_id": property_id},
                update_ops
            )
            logger.info(f"Updated property {property_id}: modified={result.modified_count}")
        
            updated_prop = await property_col.find_one({"property_id": property_id})
            if updated_prop:
                files_doc = updated_prop.get("files", {})
                mls_doc = files_doc.get("mls", {})
                comps_doc = files_doc.get("comps", {})
                
                # Overwrite our local tracking vars with DB truth
                mls_data = mls_doc
                comps_data = comps_doc
            
        else:
            # Create new property document
            new_property = {
                "property_id": property_id,
                "user_id": user_id, 
                "files": {
                    "mls": mls_data,
                    "comps": comps_data
                },
                "created_at": datetime.utcnow()
            }
            result = await property_col.insert_one(new_property)
            logger.info(f"Created new property {property_id} for user {user_id}")
            
            # Initialize empty chat history in separate collection
            chat_col = await mongo.get_chat_collection()
            await chat_col.update_one(
                {"property_id": property_id},
                {"$setOnInsert": {"property_id": property_id, "messages": []}},
                upsert=True
            )
        
        # Construct Response
        from app.model.doc_model import FileGroup, FilesStructure
        
        # Helper to safely instantiate FileGroup from dict or object
        def to_file_group(data):
            if isinstance(data, dict):
                 return FileGroup(
                     url=data.get("url", []),
                     images=[ExtractedImage(**img) if isinstance(img, dict) else img for img in data.get("images", [])],
                     total_images=data.get("total_images", 0),
                     total_pages=data.get("total_pages", 0)
                 )
            return data

        response_files = FilesStructure(
            mls=to_file_group(mls_data),
            comps=to_file_group(comps_data)
        )
        
        response = PDFUploadResponse(
            property_id=property_id,
            user_id=user_id,
            total_files=total_files,
            files=response_files,
            message=f"Successfully processed {total_files} files"
        )
        
        return success_response(response.model_dump(), 200)
        
    except Exception as e:
        logger.error(f"Error processing PDFs: {e}")
        return error_response(f"Error processing PDFs: {str(e)}", 500)

@router.put("/image/category")
async def update_image_category(
    request: Request,
    payload: dict = Body(...),
    mongo: MongoService = Depends(get_mongo_service)
):
    """Update the category of a specific image."""
    if not hasattr(request.state, 'jwt_payload'):
        return error_response("Authentication required", 401)
    
    user_id = request.state.jwt_payload.get("user_id")
    
    property_id = payload.get("property_id")
    image_id = payload.get("image_id")
    category = payload.get("category")
    
    if not property_id or not image_id or not category:
        return error_response("property_id, image_id, and category are required", 400)
        
    try:
        property_col = await mongo.get_property_data_collection()
        
        # Update image category in property document
        result = await property_col.update_one(
            {
                "property_id": property_id,
                "user_id": user_id,
                "files.mls.images.id": image_id
            },
            {"$set": {"files.mls.images.$[img].category": category}},
            array_filters=[{"img.id": image_id}]
        )
        
        # If not found in mls, try comps
        if result.matched_count == 0:
            result = await property_col.update_one(
                {
                    "property_id": property_id,
                    "user_id": user_id,
                    "files.comps.images.id": image_id
                },
                {"$set": {"files.comps.images.$[img].category": category}},
                array_filters=[{"img.id": image_id}]
            )
        
        if result.matched_count == 0:
            return error_response("Image not found", 404)
            
        return success_response({"message": "Category updated", "category": category})
        
    except Exception as e:
        logger.error(f"Error updating category: {e}")
        return error_response("Failed to update category", 500)

@router.get("/project")
async def get_user_projects(request: Request, mongo: MongoService = Depends(get_mongo_service)):
    """List all projects for the authenticated user."""
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_id = request.state.jwt_payload.get("user_id")
    if not user_id:
        return error_response("Invalid user session", 401)
        
    try:
        property_col = await mongo.get_property_data_collection()
        
        # Find all properties for this user
        logger.info(f"Querying projects for user_id: {user_id}")
        cursor = property_col.find({"user_id": user_id})
        properties = await cursor.to_list(length=100)
        
        logger.info(f"Found {len(properties)} documents for user {user_id}")

        # Convert ObjectId to string if needed (though we use property_id)
        for p in properties:
             if "_id" in p:
                 p["_id"] = str(p["_id"])

        logger.info(f"Retrieved {len(properties)} projects for user {user_id}")
        return success_response(properties)
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        return error_response("Failed to fetch projects", 500)

@router.get("/property")
async def get_property_detail(request: Request, property_id: str = Body(..., embed=True), mongo: MongoService = Depends(get_mongo_service)):
    """Get details for a specific property."""
    logger.debug(f"GET /doc/property - property_id: {property_id}")
    
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_id = request.state.jwt_payload.get("user_id")
    
    try:
        property_col = await mongo.get_property_data_collection()
        
        # Find property by ID and User ID
        property_doc = await property_col.find_one({
            "property_id": property_id,
            "user_id": user_id
        })
        
        if not property_doc:
            logger.warning(f"Project not found: {property_id} for user {user_id}")
            return error_response("Project not found", 404)
        
        logger.info(f"Retrieved project {property_id} for user {user_id}")
        
        # Fetch chat history separately
        chat_col = await mongo.get_chat_collection()
        chat_doc = await chat_col.find_one({"property_id": property_id})
        # Use simple list if not found or empty
        chat_history = chat_doc.get("messages", []) if chat_doc else []

        files_data = property_doc.get("files", {})
        
        # Handle both legacy (list) and new (dict) structure safely
        all_files = []
        if isinstance(files_data, list):
            all_files = files_data
        elif isinstance(files_data, dict):
            # safely access .get("images", []) from inner dicts if they exist
            mls_data = files_data.get("mls", {})
            if isinstance(mls_data, dict):
                all_files.extend(mls_data.get("images", []))
            elif isinstance(mls_data, list): # Legacy intermediate state fix
                all_files.extend(mls_data)
                
            comps_data = files_data.get("comps", {})
            if isinstance(comps_data, dict):
                all_files.extend(comps_data.get("images", []))
            elif isinstance(comps_data, list): # Legacy intermediate state fix
                all_files.extend(comps_data)
            
        images = []
        
        for img in all_files:
            # User requested: "do not store caption and catagory both just keep only catagory"
            # We map stored caption or category to response "category".
            # If "caption" exists in DB, use it as category if category is missing/default
            
            cat = img.get("category", "unknown")
            if cat == "uncategorized" or cat == "unknown":
                 if img.get("caption"):
                     cat = img.get("caption")

            img_response = {
                "id": img.get("id"),
                "filename": img.get("filename"),
                "page": img.get("page"),
                # "caption" removed per request
                "url": img.get("url"),
                "mime_type": img.get("mime_type"),
                "category": cat
            }
            images.append(img_response)
        
        response = {
            "property_id": property_doc["property_id"],
            "user_id": user_id,
            "images": images,
            "pdf_urls": property_doc.get("pdf_urls", []),
            "created_at": property_doc.get("created_at"),
            "chat_history": chat_history
        }
            
        return success_response(response)
        
    except Exception as e:
        logger.error(f"Error fetching project {property_id}: {e}")
        return error_response("Failed to fetch project details", 500)

@router.get("/image")
async def get_image(request: Request, image_id: str = Body(..., embed=True), mongo: MongoService = Depends(get_mongo_service)):
    """Serve an image by ID (redirect to S3 URL)."""
    try:
        from fastapi.responses import RedirectResponse
        
        property_col = await mongo.get_property_data_collection()
        
        # Need to broaden search because image matching logic below relies on file listing
        # Ideally we search specifically, but 'files.id' query might not match nested objects perfectly without proper dot notation or wildcards if schema varies
        # But we can try to find ANY doc containing the ID in the known paths
        
        property_doc = await property_col.find_one({
            "$or": [
                {"files.id": image_id},
                {"files.mls.images.id": image_id},
                {"files.comps.images.id": image_id}
            ]
        })
        
        if not property_doc:
            return error_response("Image not found", 404)
        
        files_data = property_doc.get("files", {})
        all_files = []
        if isinstance(files_data, list):
            all_files = files_data
        elif isinstance(files_data, dict):
            mls_data = files_data.get("mls", {})
            if isinstance(mls_data, dict): all_files.extend(mls_data.get("images", []))
            
            comps_data = files_data.get("comps", {})
            if isinstance(comps_data, dict): all_files.extend(comps_data.get("images", []))
            
        image = next((img for img in all_files if img["id"] == image_id), None)
        
        if not image:
            return error_response("Image not found", 404)
        
        return RedirectResponse(url=image["url"])
        
    except Exception as e:
        logger.error(f"Error fetching image {image_id}: {e}")
        return error_response("Failed to fetch image", 500)
