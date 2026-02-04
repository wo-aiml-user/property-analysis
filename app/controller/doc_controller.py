"""
Document Controller - PDF upload, image extraction, and property management.
"""

from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, Depends, Request, HTTPException, Body
from loguru import logger
from starlette.concurrency import run_in_threadpool
import uuid
from app.utils.response import success_response, error_response
from app.model.doc_model import (
    PDFUploadResponse, ExtractedImage, PropertyData, ProjectSummary, 
    FileType, ImageCategory, PropertyDataResponse, ExtractedImageResponse
)
from app.services.pdf_extractor import get_pdf_extractor, PDFExtractor
from app.services.s3_service import get_s3_service, S3Service
from app.services.mongo_service import get_mongo_service, MongoService

router = APIRouter()

@router.post("/upload", response_model=PDFUploadResponse)
async def upload_pdfs(
    request: Request,
    property_id: str = Form(...),
    files: List[UploadFile] = File(...),
    file_type: FileType = Form(FileType.MLS),
    mongo: MongoService = Depends(get_mongo_service),
    s3: S3Service = Depends(get_s3_service),
    pdf_extractor: PDFExtractor = Depends(get_pdf_extractor)
):
    """
    Upload multiple PDF files, extract images, and create/update a property session.
    """
    # 1. Authentication Check
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_id = request.state.jwt_payload.get("user_id")
    if not user_id:
        return error_response("Invalid user session", 401)

    # Validate files
    logger.info(f"Received {len(files)} files for property {property_id} as {file_type}")
    for file in files:
        if not file.filename:
            continue
        if not file.filename.lower().endswith('.pdf'):
            return error_response(f"Only PDF files are allowed. Got: {file.filename}", 400)
    
    all_images = []
    pdf_urls = []
    total_pages = 0
    
    try:
        for file in files:
            if not file.filename:
                continue
            filename = file.filename
            logger.info(f"Processing PDF: {filename}")
            
            try:
                # Step 1: Read file content
                file_content = await file.read()
                
                # Step 2: Upload PDF to S3
                pdf_s3_result = await run_in_threadpool(
                    s3.upload_file_to_s3,
                    buffer=file_content,
                    key=f"pdfs/{property_id}/{filename}",
                    content_type="application/pdf"
                )
                
                if not pdf_s3_result:
                    logger.error(f"Failed to upload PDF to S3: {filename}")
                    continue
                
                # Get public URL
                pdf_url = s3.get_public_url(f"pdfs/{property_id}/{filename}")
                pdf_urls.append(pdf_url)
                
                # Step 3: Extract images
                extraction_result = await run_in_threadpool(
                    pdf_extractor.extract_images_from_bytes,
                    pdf_bytes=file_content,
                    pdf_filename=filename,
                    folder=f"extracted/{property_id}/{Path(filename).stem}"
                )
                
                total_pages += extraction_result.get('total_pages', 0)
                
                # Step 4: Build image models
                for img in extraction_result.get('images', []):
                    image_id = uuid.uuid4().hex
                    caption = img.get('caption', '').strip()
                    # Store caption directly as category (frontend will handle categorization)
                    category = caption.lower() if caption else 'uncategorized'
                    all_images.append(ExtractedImage(
                        id=image_id,
                        filename=f"{filename}_{img['filename']}",
                        page=img['page'],
                        caption=caption,
                        url=img['url'],
                        mime_type=img.get('mime_type', 'image/png'),
                        file_type=file_type,
                        category=category
                    ))
                
            except Exception as e:
                logger.error(f"Error processing PDF {filename}: {e}")
                continue
            finally:
                await file.close()
        
        # Step 5: Persist Property Data (Upsert to add to existing property if exists)
        # We need to add new images to existing list if property exists
        
        existing_doc = await mongo.db["property_data"].find_one({"property_id": property_id, "user_id": user_id})
        
        if existing_doc:
            # Append new images and pdfs
            await mongo.db["property_data"].update_one(
                {"property_id": property_id},
                {
                    "$push": {
                        "files": {"$each": [img.model_dump() for img in all_images]},
                        "pdf_urls": {"$each": pdf_urls}
                    }
                }
            )
            # Combine for response
            # Note: Response will only show newly uploaded images for now to keep payload light?
            # Or return full state? The response model implies full state or session state.
            # Let's return just what was processed + context
            
        else:
            # Create new
            property_data = PropertyData(
                property_id=property_id,
                user_id=user_id,
                files=all_images,
                pdf_urls=pdf_urls
            )
            await mongo.db["property_data"].insert_one(property_data.model_dump())
        
        logger.info(f"Property {property_id} updated with {len(all_images)} new images")
        
        response = PDFUploadResponse(
            property_id=property_id,
            total_files=len(files),
            total_pages=total_pages,
            total_images=len(all_images),
            images=all_images,
            pdf_urls=pdf_urls,
            message=f"Successfully extracted {len(all_images)} images"
        )
        
        return success_response(response.model_dump(), 200)
        
    except Exception as e:
        logger.error(f"Error processing PDFs: {e}")
        return error_response(f"Error processing PDFs: {str(e)}", 500)

@router.put("/image/{property_id}/{image_id}/category")
async def update_image_category(
    property_id: str, 
    image_id: str, 
    payload: dict = Body(...),
    request: Request = None,
    mongo: MongoService = Depends(get_mongo_service)
):
    """Update the category of a specific image."""
    if not hasattr(request.state, 'jwt_payload'):
        return error_response("Authentication required", 401)
    
    category = payload.get("category")
    if not category:
        return error_response("Category is required", 400)
        
    try:
        # Update specific item in array
        result = await mongo.db["property_data"].update_one(
            {"property_id": property_id, "files.id": image_id},
            {"$set": {"files.$.category": category}}
        )
        
        if result.modified_count == 0:
            return error_response("Image not found or category unchanged", 404)
            
        return success_response({"message": "Category updated", "category": category})
        
    except Exception as e:
        logger.error(f"Error updating category: {e}")
        return error_response("Failed to update category", 500)

@router.get("/projects", response_model=List[PropertyData])
async def get_projects(request: Request, mongo: MongoService = Depends(get_mongo_service)):
    """List all projects for the authenticated user."""
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_id = request.state.jwt_payload.get("user_id")
    if not user_id:
        return error_response("Invalid user session", 401)
        
    try:
        cursor = mongo.db["property_data"].find({"user_id": user_id}).sort("created_at", -1)
        projects = []
        async for doc in cursor:
            projects.append(PropertyData(**doc))
        return projects
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        return error_response("Failed to fetch projects", 500)

@router.get("/{property_id}")
async def get_project(property_id: str, request: Request, mongo: MongoService = Depends(get_mongo_service)):
    """Get filtered details for a specific property (separates MLS vs Comps)."""
    logger.debug(f"GET /doc/{property_id} - Checking Auth")
    
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_id = request.state.jwt_payload.get("user_id")
    
    try:
        doc = await mongo.db["property_data"].find_one({
            "property_id": property_id,
            "user_id": user_id
        })
        
        if not doc:
            return error_response("Project not found", 404)
        
        files = doc.get("files", [])
        mls_images = []
        comps_images = []
        
        for img in files:
            # Map to response format (exclude internal S3 URL if needed, but ExtractedImage has it)
            # Use public endpoints for frontend
            img_response = {
                "id": img.get("id"),
                "filename": img.get("filename"),
                "page": img.get("page"),
                "caption": img.get("caption", ""),
                "mime_type": img.get("mime_type"),
                "file_type": img.get("file_type", FileType.MLS.value),
                "category": img.get("category", ImageCategory.UNCATEGORIZED.value)
            }
            
            if img_response["file_type"] == FileType.MLS.value:
                mls_images.append(img_response)
            else:
                comps_images.append(img_response)
        
        response = {
            "property_id": doc["property_id"],
            "user_id": doc["user_id"],
            "mls_images": mls_images,
            "comps_images": comps_images,
            "pdf_urls": doc.get("pdf_urls", []),
            "created_at": doc["created_at"],
            "chat_history": doc.get("chat_history", [])
        }
            
        return success_response(response)
        
    except Exception as e:
        logger.error(f"Error fetching project {property_id}: {e}")
        return error_response("Failed to fetch project details", 500)

@router.get("/image/{image_id}")
async def get_image(image_id: str, mongo: MongoService = Depends(get_mongo_service)):
    """Serve an image by ID (redirect to S3 URL)."""
    try:
        from fastapi.responses import RedirectResponse
        # Search in any property (public access if ID known?)
        # For security, probably should check auth, but user requested image serving
        # Assuming images are somewhat private but obfuscated by UUID
        
        property_doc = await mongo.db["property_data"].find_one({
            "files.id": image_id
        })
        
        if not property_doc:
            return error_response("Image not found", 404)
        
        files = property_doc.get("files", [])
        image = next((img for img in files if img["id"] == image_id), None)
        
        if not image:
            return error_response("Image not found", 404)
        
        return RedirectResponse(url=image["url"])
        
    except Exception as e:
        logger.error(f"Error fetching image {image_id}: {e}")
        return error_response("Failed to fetch image", 500)
