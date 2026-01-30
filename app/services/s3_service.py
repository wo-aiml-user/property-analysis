"""
AWS S3 Storage Service.
Handles image upload and download for S3.
Based on official AWS Boto3 documentation.
"""

import boto3
from botocore.exceptions import ClientError
from typing import Optional
import uuid
import io
from loguru import logger
from app.config import settings


class S3Service:
    """Service for AWS S3 operations."""
    
    def __init__(self):
        """Initialize S3 client with credentials from settings."""
        if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
            logger.warning("AWS credentials not configured - S3 operations will fail")
            self.client = None
            return
        
        if not settings.AWS_BUCKET_NAME:
            logger.warning("AWS_BUCKET_NAME not configured")
            self.client = None
            return
        
        # Initialize S3 client
        self.client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION
        )
        self.bucket_name = settings.AWS_BUCKET_NAME
        self.region = settings.AWS_REGION
        
        logger.info(f"S3 service initialized for bucket: {self.bucket_name} in {self.region}")
    
    def _generate_key(self, folder: str, filename: str, extension: str = "png") -> str:
        """Generate a unique S3 object key."""
        unique_id = str(uuid.uuid4())[:8]
        folder = folder.strip('/')
        return f"{folder}/{unique_id}_{filename}.{extension}"
    
    def upload_file_to_s3(
        self,
        buffer: bytes,
        key: str,
        content_type: str = "application/octet-stream"
    ) -> Optional[str]:
        """
        Upload file to S3 bucket.
        
        Args:
            buffer: File-like object (Bytes) containing the file data
            key: The S3 object key (path/filename in the bucket)
            content_type: MIME type (defaults to application/octet-stream)
            
        Returns:
            S3 key on success, None on failure
        """
        if not self.client:
            logger.error("S3 client not initialized")
            return None
        
        try:
            # Create file-like object from bytes
            file_obj = io.BytesIO(buffer)
            
            # Upload using upload_fileobj (streams directly to S3)
            self.client.upload_fileobj(
                file_obj,
                self.bucket_name,
                key,
                ExtraArgs={
                    'ContentType': content_type
                }
            )
            
            logger.debug(f"Uploaded to S3: {key}")
            return key
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(f"S3 upload error ({error_code}): {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error uploading to S3: {e}")
            return None
    
    def get_file_from_s3(self, key: str) -> Optional[bytes]:
        """
        Download file from S3 and return as bytes.
        Alias for get_s3_file_buffer for clearer naming.
        """
        return self.get_s3_file_buffer(key)

    def get_s3_file_buffer(
        self,
        key: str,
        bucket_name: str = None
    ) -> Optional[bytes]:
        """
        Download file from S3 and return as bytes buffer.
        
        Args:
            key: S3 object key (path/filename)
            bucket_name: Optional bucket name (uses default if not provided)
            
        Returns:
            Bytes buffer containing the file content, None on failure
        """
        if not self.client:
            logger.error("S3 client not initialized")
            return None
        
        bucket = bucket_name or self.bucket_name
        
        try:
            buffer = io.BytesIO()
            self.client.download_fileobj(bucket, key, buffer)
            buffer.seek(0)
            return buffer.read()
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            
            if error_code == 'NoSuchKey':
                logger.error(f"S3 object not found: {key}")
            elif error_code == 'NoSuchBucket':
                logger.error(f"S3 bucket not found: {bucket}")
            elif error_code == 'AccessDenied':
                logger.error(f"Access denied to S3 object: {key}")
            else:
                logger.error(f"S3 download error ({error_code}): {e}")
            
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading from S3: {e}")
            return None
    
    def get_public_url(self, key: str) -> str:
        """
        Get public URL for an S3 object.
        
        Args:
            key: S3 object key
            
        Returns:
            Public URL string
        """
        return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{key}"
    
    def upload_image(
        self,
        image_bytes: bytes,
        folder: str = "images",
        filename: str = "image",
        mime_type: str = "image/png"
    ) -> Optional[dict]:
        """
        Convenience method to upload image bytes with auto-generated key.
        
        Args:
            image_bytes: Raw image bytes
            folder: S3 folder/prefix
            filename: Base filename
            mime_type: Image MIME type
            
        Returns:
            Dict with url (Object URL), key and bucket, or None on failure
        """
        # Determine extension from mime type
        ext_map = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/gif": "gif",
            "image/webp": "webp"
        }
        extension = ext_map.get(mime_type, "png")
        
        # Generate unique key
        key = self._generate_key(folder, filename, extension)
        
        # Upload
        result_key = self.upload_file_to_s3(image_bytes, key, mime_type)
        
        if result_key:
            # Return simple Object URL (requires bucket policy for public access)
            return {
                "key": result_key,
                "url": self.get_public_url(result_key),
                "bucket": self.bucket_name
            }
        return None
    
    def delete_object(self, key: str) -> bool:
        """Delete an object from S3."""
        if not self.client:
            return False
        
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=key)
            logger.debug(f"Deleted from S3: {key}")
            return True
        except ClientError as e:
            logger.error(f"S3 delete error: {e}")
            return False
    
    def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600
    ) -> Optional[str]:
        """
        Generate a presigned URL for temporary access.
        
        Args:
            key: S3 object key
            expiration: URL expiration in seconds (default 1 hour)
            
        Returns:
            Presigned URL or None
        """
        if not self.client:
            return None
        
        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            logger.error(f"Error generating presigned URL: {e}")
            return None


# Singleton instance
_s3_service: Optional[S3Service] = None


def get_s3_service() -> S3Service:
    """Get or create the S3 service singleton."""
    global _s3_service
    if _s3_service is None:
        _s3_service = S3Service()
    return _s3_service
