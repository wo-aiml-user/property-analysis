"""
MongoDB Service for database operations.
"""

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection
from typing import Optional
from loguru import logger
from app.config import settings


class MongoService:
    """MongoDB connection and database operations."""
    
    def __init__(self):
        """Initialize MongoDB client."""
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None
        self._connect()
    
    def _connect(self):
        """Establish connection to MongoDB."""
        try:
            if not settings.MONGODB_URI:
                logger.warning("MONGODB_URI not configured - MongoDB operations will fail")
                return
            
            self.client = MongoClient(settings.MONGODB_URI)
            self.db = self.client[settings.MONGODB_DB_NAME]
            
            # Test connection
            self.client.admin.command('ping')
            logger.info(f"MongoDB connected to database: {settings.MONGODB_DB_NAME}")
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            self.client = None
            self.db = None
    
    def get_collection(self, collection_name: str) -> Optional[Collection]:
        """Get a MongoDB collection."""
        if not self.db:
            logger.error("MongoDB database not initialized")
            return None
        return self.db[collection_name]
    
    def get_users_collection(self) -> Optional[Collection]:
        """Get the users collection."""
        return self.get_collection(settings.MONGODB_COLLECTION_NAME)
    
    def close(self):
        """Close MongoDB connection."""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")


# Singleton instance
_mongo_service: Optional[MongoService] = None


def get_mongo_service() -> MongoService:
    """Get or create the MongoDB service singleton."""
    global _mongo_service
    if _mongo_service is None:
        _mongo_service = MongoService()
    return _mongo_service
