"""
MongoDB Service for database operations (Async).
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional
from loguru import logger
from app.config import settings
from datetime import datetime
from passlib.context import CryptContext

class MongoService:
    """Async MongoDB connection and database operations."""
    
    _instance: Optional['MongoService'] = None
    
    def __init__(self):
        """Initialize MongoDB client."""
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        
    async def connect(self):
        """Establish connection to MongoDB."""
        if self.client:
            return

        try:
            if not settings.MONGODB_URI:
                logger.warning("MONGODB_URI not configured - MongoDB operations will fail")
                return
            
            # Connect to MongoDB
            self.client = AsyncIOMotorClient(settings.MONGODB_URI)
            self.db = self.client[settings.MONGODB_DB_NAME]
            
            # Test connection
            await self.client.admin.command('ping')
            logger.info("MongoDB connection successful")
            
            # Ensure indexes
            await self._ensure_indexes()
            
            logger.info(f"MongoDB ready: {settings.MONGODB_DB_NAME}")
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            self.client = None
            self.db = None
            
    async def _ensure_indexes(self):
        """Create necessary indexes."""
        if self.db is None:
            return
            
        try:
            # Users collection indexes
            users = self.db[settings.MONGODB_COLLECTION_NAME]
            await users.create_index("email", unique=True)
            
            # Refresh tokens collection indexes - NEW
            tokens = self.db["refresh_tokens"]
            await tokens.create_index("token_hash", unique=True)
            await tokens.create_index("user_id")
            # Auto-expire tokens
            await tokens.create_index("expires_at", expireAfterSeconds=0)
            
            # Property data collection - cleanup incorrect index
            property_data = self.db["property_data"]
            try:
                # Check if incorrect email_1 index exists and drop it
                indexes = await property_data.list_indexes().to_list(length=None)
                index_names = [idx['name'] for idx in indexes]
                
                if 'email_1' in index_names:
                    logger.warning("Found incorrect email_1 index on property_data, dropping it...")
                    await property_data.drop_index('email_1')
                    logger.info("Successfully dropped email_1 index from property_data")
            except Exception as e:
                logger.debug(f"Index cleanup check: {e}")
            
            logger.info("MongoDB indexes verified")
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")

    
    def get_collection(self, collection_name: str): # -> AsyncIOMotorCollection
        """Get a MongoDB collection."""
        if self.db is None:
            logger.error("MongoDB database not initialized")
            # Return a generic proxy or raise, but for now returning None might break callers not checking
            # Ideally we should raise specific exception
            return None
        return self.db[collection_name]
    
    def get_users_collection(self):
        """Get the users collection."""
        return self.get_collection(settings.MONGODB_COLLECTION_NAME)

    def close(self):
        """Close MongoDB connection."""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

# Singleton accessor
async def get_mongo_service() -> MongoService:
    """Get the MongoDB service singleton, initializing connection if needed."""
    if MongoService._instance is None:
        MongoService._instance = MongoService()
        await MongoService._instance.connect()
    return MongoService._instance
