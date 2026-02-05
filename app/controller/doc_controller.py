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
    files: List[UploadFile] = File(...),
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
    user_email = request.state.jwt_payload.get("email")
    
    if not user_id or not user_email:
        return error_response("Invalid user session", 401)

    # Validate files
    logger.info(f"Received {len(files)} files for property {property_id}")
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
                    all_images.append(ExtractedImage(
                        id=image_id,
                        filename=f"{filename}_{img['filename']}",
                        page=img['page'],
                        caption=caption,
                        url=img['url'],
                        mime_type=img.get('mime_type', 'image/png'),
                        category='uncategorized'  # Frontend handles categorization
                    ))
                
            except Exception as e:
                logger.error(f"Error processing PDF {filename}: {e}")
                continue
            finally:
                await file.close()
        
        # Step 5: Persist Property Data in user's properties array
        # Find the user document and add/update property in their properties array
        
        property_data_col = await mongo.get_property_data_collection()
        
        # Check if user has this property already
        user_doc = await property_data_col.find_one({
            "email": user_email,  # Use email from JWT
            "properties.property_id": property_id
        })
        
        if user_doc:
            # Property exists, append new images and pdfs to existing property
            result = await property_data_col.update_one(
                {
                    "email": user_email,
                    "properties.property_id": property_id
                },
                {
                    "$push": {
                        "properties.$.files": {"$each": [img.model_dump() for img in all_images]},
                        "properties.$.pdf_urls": {"$each": pdf_urls}
                    }
                }
            )
            logger.info(f"Updated existing property {property_id} with {len(all_images)} new images (matched: {result.matched_count}, modified: {result.modified_count})")
        else:
            # Property doesn't exist, create new property in user's properties array
            new_property = {
                "property_id": property_id,
                "files": [img.model_dump() for img in all_images],
                "pdf_urls": pdf_urls,
                "created_at": datetime.utcnow(),
                "chat_history": []
            }
            
            result = await property_data_col.update_one(
                {"email": user_email},
                {"$push": {"properties": new_property}}
            )
            logger.info(f"Created new property {property_id} with {len(all_images)} images (matched: {result.matched_count}, modified: {result.modified_count})")
        
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
    
    user_id = request.state.jwt_payload.get("user_id")
    category = payload.get("category")
    if not category:
        return error_response("Category is required", 400)
        
    try:
        property_data_col = await mongo.get_property_data_collection()
        
        # Update image category in nested properties array
        result = await property_data_col.update_one(
            {
                "email": user_id,
                "properties.property_id": property_id,
                "properties.files.id": image_id
            },
            {"$set": {"properties.$[prop].files.$[img].category": category}},
            array_filters=[
                {"prop.property_id": property_id},
                {"img.id": image_id}
            ]
        )
        
        if result.modified_count == 0:
            return error_response("Image not found or category unchanged", 404)
            
        return success_response({"message": "Category updated", "category": category})
        
    except Exception as e:
        logger.error(f"Error updating category: {e}")
        return error_response("Failed to update category", 500)

@router.get("/projects")
async def get_projects(request: Request, mongo: MongoService = Depends(get_mongo_service)):
    """List all projects for the authenticated user."""
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_email = request.state.jwt_payload.get("email")
    if not user_email:
        return error_response("Invalid user session", 401)
        
    try:
        property_data_col = await mongo.get_property_data_collection()
        user_doc = await property_data_col.find_one({"email": user_email})
        
        if not user_doc or "properties" not in user_doc:
            return success_response([])
        
        # Return user's properties array
        properties = user_doc.get("properties", [])
        return success_response(properties)
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        return error_response("Failed to fetch projects", 500)

@router.post("/project")
async def get_project(request: Request, property_id: str = Body(..., embed=True), mongo: MongoService = Depends(get_mongo_service)):
    """Get details for a specific property."""
    logger.debug(f"POST /doc/project - property_id: {property_id}")
    
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_email = request.state.jwt_payload.get("email")
    
    try:
        property_data_col = await mongo.get_property_data_collection()
        
        # Find user and extract specific property from properties array
        user_doc = await property_data_col.find_one({
            "email": user_email,
            "properties.property_id": property_id
        })
        
        if not user_doc:
            return error_response("Project not found", 404)
        
        # Find the specific property in the properties array
        property_doc = None
        for prop in user_doc.get("properties", []):
            if prop.get("property_id") == property_id:
                property_doc = prop
                break
        
        if not property_doc:
            return error_response("Project not found", 404)
        
        files = property_doc.get("files", [])
        images = []
        
        for img in files:
            img_response = {
                "id": img.get("id"),
                "filename": img.get("filename"),
                "page": img.get("page"),
                "caption": img.get("caption", ""),
                "url": img.get("url"),
                "mime_type": img.get("mime_type"),
                "category": img.get("category", "uncategorized")
            }
            images.append(img_response)
        
        response = {
            "property_id": property_doc["property_id"],
            "user_id": user_email,
            "images": images,
            "pdf_urls": property_doc.get("pdf_urls", []),
            "created_at": property_doc.get("created_at"),
            "chat_history": property_doc.get("chat_history", [])
        }
            
        return success_response(response)
        
    except Exception as e:
        logger.error(f"Error fetching project {property_id}: {e}")
        return error_response("Failed to fetch project details", 500)

@router.post("/image")
async def get_image(request: Request, image_id: str = Body(..., embed=True), mongo: MongoService = Depends(get_mongo_service)):
    """Serve an image by ID (redirect to S3 URL)."""
    try:
        from fastapi.responses import RedirectResponse
        
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
