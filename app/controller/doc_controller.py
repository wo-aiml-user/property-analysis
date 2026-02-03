"""
Document Controller - PDF upload and image extraction.
Workflow: Upload PDF to S3 -> Download bytes -> Extract images -> Upload images to S3
"""

from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, Depends, Request, HTTPException
from loguru import logger
from starlette.concurrency import run_in_threadpool
import uuid
from app.utils.response import success_response, error_response
from app.model.doc_model import PDFUploadResponse, ExtractedImage, PropertyData, ProjectSummary
from app.services.pdf_extractor import get_pdf_extractor
from app.services.s3_service import get_s3_service
from app.services.mongo_service import get_mongo_service, MongoService

router = APIRouter()

@router.post("/upload", response_model=PDFUploadResponse)
async def upload_pdfs(
    request: Request,
    property_id: str = Form(...),
    files: List[UploadFile] = File(...),
    mongo: MongoService = Depends(get_mongo_service)
):
    """
    Upload multiple PDF files, extract images, and create a property session.
    
    Parameters:
    - property_id: Unique ID for the property (frontend generated)
    - files: List of PDF files
    """
    # 1. Authentication Check
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_id = request.state.jwt_payload.get("user_id")
    if not user_id:
        return error_response("Invalid user session", 401)

    # Validate files
    logger.info(f"Received {len(files)} files")
    for file in files:
        logger.info(f"Checking file: '{file.filename}' (ContentType: {file.content_type})")
        if not file.filename:
            # Skip empty entries if any
            continue
            
        if not file.filename.lower().endswith('.pdf'):
            return JSONResponse(content={"error": f"Only PDF files are allowed. Got: {file.filename}"}, status_code=400)
    
    all_images = []
    pdf_urls = []
    total_pages = 0
    
    try:
        s3_service = get_s3_service()
        pdf_extractor = get_pdf_extractor()
        
        for file in files:
            if not file.filename:
                continue
            filename = file.filename
            logger.info(f"Processing PDF: {filename}")
            
            try:
                # Step 1: Read file content (Async IO)
                file_content = await file.read()
                
                # Step 2: Upload PDF to S3 (Blocking -> Threadpool)
                # Note: S3 upload can be slow, better to offload
                pdf_s3_result = await run_in_threadpool(
                    s3_service.upload_file_to_s3,
                    buffer=file_content,
                    key=f"pdfs/{property_id}/{filename}", # Organize by property_id
                    content_type="application/pdf"
                )
                
                if not pdf_s3_result:
                    logger.error(f"Failed to upload PDF to S3: {filename}")
                    continue
                
                # Get and store public URL
                pdf_url = s3_service.get_public_url(f"pdfs/{property_id}/{filename}")
                pdf_urls.append(pdf_url)
                
                # Step 3: Download PDF bytes from S3 (Blocking -> Threadpool)
                # STRICT FLOW: Upload -> Download -> Extract
                logger.info(f"Downloading PDF from S3: {f'pdfs/{property_id}/{filename}'}")
                pdf_bytes = await run_in_threadpool(
                    s3_service.get_file_from_s3,
                    key=f"pdfs/{property_id}/{filename}"
                )
                
                if not pdf_bytes:
                    logger.error(f"Failed to download PDF from S3: {filename}")
                    continue 
                
                # Step 4: Extract images (CPU Intensive -> Threadpool)
                extraction_result = await run_in_threadpool(
                    pdf_extractor.extract_images_from_bytes,
                    pdf_bytes=pdf_bytes,
                    pdf_filename=filename,
                    folder=f"extracted/{property_id}/{Path(filename).stem}" # Organize by property_id
                )
                
                total_pages += extraction_result.get('total_pages', 0)
                
                # Step 5: Build response
                for img in extraction_result.get('images', []):
                    image_id = uuid.uuid4().hex  # Generate unique ID
                    all_images.append(ExtractedImage(
                        id=image_id,
                        filename=f"{filename}_{img['filename']}",
                        page=img['page'],
                        caption=img.get('caption', ''),
                        url=img['url'],
                        mime_type=img.get('mime_type', 'image/png')
                    ))
                
            except Exception as e:
                logger.error(f"Error processing PDF {filename}: {e}")
                continue
            finally:
                await file.close()
        
        # Step 6: Persist Property Data (Async)
        property_data = PropertyData(
            property_id=property_id,
            user_id=user_id,
            files=all_images,
            pdf_urls=pdf_urls
        )
        
        # Store in 'property_data' collection
        await mongo.db["property_data"].update_one(
            {"property_id": property_id},
            {"$set": property_data.model_dump()},
            upsert=True
        )
        
        logger.info(f"Property {property_id} saved with {len(all_images)} images")
        
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

@router.get("/projects", response_model=List[PropertyData])
async def get_projects(request: Request, mongo: MongoService = Depends(get_mongo_service)):
    """List all projects for the authenticated user (Full Schema)."""
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_id = request.state.jwt_payload.get("user_id")
    if not user_id:
        return error_response("Invalid user session", 401)
        
    try:
        cursor = mongo.db["property_data"].find({"user_id": user_id}).sort("created_at", -1)
        projects = []
        
        async for doc in cursor:
            # Migration: Generate IDs for files that don't have them
            needs_update = False
            for file_data in doc.get("files", []):
                if not file_data.get("id"):
                    file_data["id"] = uuid.uuid4().hex
                    needs_update = True
            
            # Update document if IDs were generated
            if needs_update:
                await mongo.db["property_data"].update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"files": doc["files"]}}
                )
            
            projects.append(PropertyData(**doc))
            
        return projects
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        return error_response("Failed to fetch projects", 500)

@router.get("/{property_id}")
async def get_project(property_id: str, request: Request, mongo: MongoService = Depends(get_mongo_service)):
    """Get full details for a specific property."""
    if not hasattr(request.state, "jwt_payload") or not request.state.jwt_payload:
        return error_response("Authentication required", 401)
        
    user_id = request.state.jwt_payload.get("user_id")
    if not user_id:
        return error_response("Invalid user session", 401)
        
    try:
        doc = await mongo.db["property_data"].find_one({
            "property_id": property_id,
            "user_id": user_id
        })
        
        if not doc:
            return error_response("Project not found", 404)
        
        # Convert to PropertyData to validate, then to response model
        property_data = PropertyData(**doc)
        
        # Create response without S3 URLs
        from app.model.doc_model import PropertyDataResponse, ExtractedImageResponse
        response = PropertyDataResponse(
            property_id=property_data.property_id,
            user_id=property_data.user_id,
            files=[
                ExtractedImageResponse(
                    id=img.id,
                    filename=img.filename,
                    page=img.page,
                    caption=img.caption,
                    mime_type=img.mime_type
                ) for img in property_data.files
            ],
            pdf_urls=property_data.pdf_urls,
            created_at=property_data.created_at,
            chat_history=property_data.chat_history
        )
            
        return success_response(response.model_dump())
        
    except Exception as e:
        logger.error(f"Error fetching project {property_id}: {e}")
        return error_response("Failed to fetch project details", 500)

@router.get("/image/{image_id}")
async def get_image(image_id: str, mongo: MongoService = Depends(get_mongo_service)):
    """Serve an image by ID (redirect to S3 URL). Public endpoint but verifies image exists."""
    try:
        # Find the property that contains this image (no user_id filter since it's public)
        from fastapi.responses import RedirectResponse
        property_doc = await mongo.db["property_data"].find_one({
            "files.id": image_id
        })
        
        if not property_doc:
            return error_response("Image not found", 404)
        
        # Find the specific image
        property_data = PropertyData(**property_doc)
        image = next((img for img in property_data.files if img.id == image_id), None)
        
        if not image:
            return error_response("Image not found", 404)
        
        # Redirect to S3 URL
        return RedirectResponse(url=image.url)
        
    except Exception as e:
        logger.error(f"Error fetching image {image_id}: {e}")
        return error_response("Failed to fetch image", 500)
