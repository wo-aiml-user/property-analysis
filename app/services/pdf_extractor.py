"""
PDF Image Extraction Service.
Extracts images and captions from PDF files using pdfplumber.
Uploads extracted images to S3 and returns URLs.
"""

import pdfplumber
import io
from pathlib import Path
from typing import Dict, Any
from loguru import logger
from app.services.s3_service import get_s3_service


class PDFExtractor:
    """Service for extracting images from PDF files."""
    
    def __init__(self):
        """Initialize the PDF extractor."""
        self.s3_service = get_s3_service()
        logger.info("PDFExtractor initialized")
    
    def extract_images_with_urls(
        self,
        pdf_path: str,
        folder: str = "extracted",
        caption_offset: int = 30
    ) -> Dict[str, Any]:
        """
        Extract all images from a PDF and upload to S3.
        
        Args:
            pdf_path: Path to the PDF file
            folder: S3 folder prefix for uploads
            caption_offset: Pixels below image to look for caption text
            
        Returns:
            Dict with total_pages and images list (each with S3 URL)
        """
        results = {
            "pdf_filename": Path(pdf_path).name,
            "total_pages": 0,
            "images": []
        }
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                results["total_pages"] = len(pdf.pages)
                
                for page_num, page in enumerate(pdf.pages):
                    images = page.images
                    if not images:
                        continue
                    
                    sorted_images = sorted(images, key=lambda x: (x['top'], x['x0']))
                    
                    for img_num, img in enumerate(sorted_images):
                        try:
                            image_data = self._extract_and_upload_image(
                                page=page,
                                img=img,
                                page_num=page_num,
                                img_num=img_num,
                                folder=folder,
                                caption_offset=caption_offset
                            )
                            
                            if image_data:
                                results["images"].append(image_data)
                                
                        except Exception as e:
                            logger.warning(f"Failed to extract image {img_num} on page {page_num}: {e}")
                            continue
                
        except Exception as e:
            logger.error(f"Error processing PDF {pdf_path}: {e}")
            raise
        
        logger.info(f"Extracted {len(results['images'])} images from {pdf_path}")
        return results
    
    def extract_images_from_bytes(
        self,
        pdf_bytes: bytes,
        pdf_filename: str,
        folder: str = "extracted",
        caption_offset: int = 30
    ) -> Dict[str, Any]:
        """
        Extract all images from PDF bytes (e.g., downloaded from S3) and upload to S3.
        
        Args:
            pdf_bytes: PDF file content as bytes
            pdf_filename: Original filename for metadata
            folder: S3 folder prefix for uploads
            caption_offset: Pixels below image to look for caption text
            
        Returns:
            Dict with total_pages and images list (each with S3 URL)
        """
        results = {
            "pdf_filename": pdf_filename,
            "total_pages": 0,
            "images": []
        }
        
        try:
            # Open PDF from bytes using BytesIO
            pdf_stream = io.BytesIO(pdf_bytes)
            
            with pdfplumber.open(pdf_stream) as pdf:
                results["total_pages"] = len(pdf.pages)
                
                for page_num, page in enumerate(pdf.pages):
                    images = page.images
                    if not images:
                        continue
                    
                    sorted_images = sorted(images, key=lambda x: (x['top'], x['x0']))
                    
                    for img_num, img in enumerate(sorted_images):
                        try:
                            image_data = self._extract_and_upload_image(
                                page=page,
                                img=img,
                                page_num=page_num,
                                img_num=img_num,
                                folder=folder,
                                caption_offset=caption_offset
                            )
                            
                            if image_data:
                                results["images"].append(image_data)
                                
                        except Exception as e:
                            logger.warning(f"Failed to extract image {img_num} on page {page_num}: {e}")
                            continue
                
        except Exception as e:
            logger.error(f"Error processing PDF {pdf_filename} from bytes: {e}")
            raise
        
        logger.info(f"Extracted {len(results['images'])} images from {pdf_filename}")
        return results
    
    def _extract_and_upload_image(
        self,
        page,
        img: Dict,
        page_num: int,
        img_num: int,
        folder: str,
        caption_offset: int
    ) -> Dict[str, Any]:
        """Extract a single image from a PDF page and upload to S3."""
        img_bbox = (img['x0'], img['top'], img['x1'], img['bottom'])
        
        # Calculate image dimensions
        img_width = img['x1'] - img['x0']
        img_height = img['bottom'] - img['top']
        img_area = img_width * img_height
        
        # Filter out small images (logos, icons, etc.)
        # Lowered thresholds to capture house photos while filtering tiny logos
        # Most house photos in PDFs are at least 150x100 or larger
        MIN_WIDTH = 150
        MIN_HEIGHT = 100
        MIN_AREA = 15000  # 150x100 = 15,000 pixels
        
        if img_width < MIN_WIDTH or img_height < MIN_HEIGHT or img_area < MIN_AREA:
            logger.debug(
                f"Skipping small image on page {page_num + 1}: "
                f"{img_width:.0f}x{img_height:.0f} (area: {img_area:.0f})"
            )
            return None
        
        logger.info(
            f"Processing image on page {page_num + 1}: "
            f"{img_width:.0f}x{img_height:.0f} (area: {img_area:.0f})"
        )
        
        # Extract caption
        caption_bbox = (
            max(0, img['x0']),
            img['bottom'],
            min(page.width, img['x1']),
            min(page.height, img['bottom'] + caption_offset)
        )
        
        try:
            caption_region = page.crop(caption_bbox)
            caption = caption_region.extract_text() or ""
            caption = caption.strip()
        except Exception:
            caption = ""
        
        # Extract image as bytes
        try:
            img_obj = page.crop(img_bbox).to_image(resolution=200)
            buffer = io.BytesIO()
            img_obj.save(buffer, format='PNG')
            buffer.seek(0)
            image_bytes = buffer.read()
        except Exception as e:
            logger.warning(f"Could not extract image: {e}")
            return None
        
        img_filename = f"page{page_num + 1}_img{img_num + 1}"
        
        # Upload to S3
        s3_result = self.s3_service.upload_image(
            image_bytes=image_bytes,
            folder=folder,
            filename=img_filename,
            mime_type="image/png"
        )
        
        if s3_result:
            return {
                "filename": f"{img_filename}.png",
                "page": page_num + 1,
                "caption": caption,
                "url": s3_result["url"],
                "mime_type": "image/png"
            }
        else:
            logger.warning("S3 upload failed")
            return None


# Singleton instance
_pdf_extractor = None


def get_pdf_extractor() -> PDFExtractor:
    """Get or create the PDF extractor singleton."""
    global _pdf_extractor
    if _pdf_extractor is None:
        _pdf_extractor = PDFExtractor()
    return _pdf_extractor
