"""
Document Controller - PDF upload and image extraction.
Workflow: Upload PDF to S3 -> Download bytes -> Extract images -> Upload images to S3
"""

from pathlib import Path
from typing import List
from fastapi import APIRouter, UploadFile, File
from loguru import logger

from app.utils.response import success_response, error_response
from app.model.doc_model import PDFUploadResponse, ExtractedImage
from app.services.pdf_extractor import get_pdf_extractor
from app.services.s3_service import get_s3_service


router = APIRouter()


@router.post("/upload", response_model=PDFUploadResponse)
async def upload_pdfs(files: List[UploadFile] = File(...)):
    """
    Upload multiple PDF files to S3, download, extract images, and upload images to S3.
    
    Workflow:
    1. Upload PDF to S3 (pdfs/ folder)
    2. Download PDF bytes from S3
    3. Parse PDF and extract images
    4. Upload extracted images to S3
    5. Return image URLs and metadata
    
    Parameters:
    - files: List of PDF files to upload
    
    Returns:
    - total_files: Number of PDFs processed
    - total_pages: Total pages across all PDFs
    - total_images: Number of extracted images
    - images: Array of extracted images with:
        - filename: Image filename
        - page: Page number where image was found
        - caption: Extracted caption/name
        - url: S3 public URL
    """
    # Validate files
    for file in files:
        if not file.filename.endswith('.pdf'):
            return error_response(f"Only PDF files are allowed. Got: {file.filename}", 400)
    
    all_images = []
    total_pages = 0
    
    try:
        s3_service = get_s3_service()
        pdf_extractor = get_pdf_extractor()
        
        for file in files:
            filename = file.filename
            logger.info(f"Processing PDF: {filename}")
            
            try:
                # Step 1: Read file content
                file_content = await file.read()
                
                # Step 2: Upload PDF to S3
                pdf_s3_result = s3_service.upload_file_to_s3(
                    buffer=file_content,
                    key=f"pdfs/{filename}",
                    content_type="application/pdf"
                )
                
                if not pdf_s3_result:
                    logger.error(f"Failed to upload PDF to S3: {filename}")
                    continue
                
                logger.info(f"PDF uploaded to S3: {pdf_s3_result}")
                
                # Step 3: Download PDF bytes from S3
                pdf_bytes = s3_service.get_s3_file_buffer(pdf_s3_result)
                
                if not pdf_bytes:
                    logger.error(f"Failed to download PDF from S3: {filename}")
                    continue
                
                # Step 4: Extract images from PDF bytes
                extraction_result = pdf_extractor.extract_images_from_bytes(
                    pdf_bytes=pdf_bytes,
                    pdf_filename=filename,
                    folder=f"extracted/{Path(filename).stem}"
                )
                
                total_pages += extraction_result.get('total_pages', 0)
                
                # Step 5: Build response with extracted images
                for img in extraction_result.get('images', []):
                    all_images.append(ExtractedImage(
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
        
        logger.info(f"Extracted {len(all_images)} images from {len(files)} PDF(s)")
        
        response = PDFUploadResponse(
            total_files=len(files),
            total_pages=total_pages,
            total_images=len(all_images),
            images=all_images,
            message=f"Successfully extracted {len(all_images)} images from {len(files)} PDF(s)"
        )
        
        return success_response(response.model_dump(), 200)
        
    except Exception as e:
        logger.error(f"Error processing PDFs: {e}")
        return error_response(f"Error processing PDFs: {str(e)}", 500)
