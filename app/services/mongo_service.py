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
    
    async def _ensure_collection_exists(self, collection_name: str):
        """Ensure a collection exists, create if it doesn't."""
        if self.db is None:
            logger.error("Database not initialized")
            return False
            
        try:
            # List existing collections
            existing_collections = await self.db.list_collection_names()
            
            if collection_name not in existing_collections:
                # Create the collection
                await self.db.create_collection(collection_name)
                logger.info(f"Created collection: {collection_name}")
            else:
                pass 
                # logger.debug(f"Collection already exists: {collection_name}")
                
            return True
        except Exception as e:
            logger.error(f"Error ensuring collection {collection_name} exists: {e}")
            return False
            
    async def _ensure_indexes(self):
        """Create necessary indexes."""
        if self.db is None:
            return
            
        try:
            # Ensure property_data collection exists
            await self._ensure_collection_exists(settings.MONGODB_COLLECTION_NAME)
            
            # Property_data collection indexes (stores both users and properties)
            property_data = self.db[settings.MONGODB_COLLECTION_NAME]
            
            # Get existing indexes
            existing_indexes = await property_data.index_information()
            
            # Create email index only if it doesn't exist
            if "email_1" not in existing_indexes:
                await property_data.create_index("email", unique=True, sparse=True)
                logger.info("Created email index on property_data")
            else:
                logger.debug("Email index already exists, skipping creation")
            
            # Create properties.property_id index only if it doesn't exist
            if "properties.property_id_1" not in existing_indexes:
                await property_data.create_index("properties.property_id")
                logger.info("Created properties.property_id index")
            else:
                logger.debug("Properties.property_id index already exists, skipping creation")
            
            # Ensure refresh_tokens collection exists
            await self._ensure_collection_exists("refresh_tokens")
            
            # Refresh tokens collection indexes
            tokens = self.db["refresh_tokens"]
            existing_token_indexes = await tokens.index_information()
            
            # Create token_hash index only if it doesn't exist
            if "token_hash_1" not in existing_token_indexes:
                await tokens.create_index("token_hash", unique=True)
                logger.info("Created token_hash index")
            else:
                logger.debug("Token_hash index already exists, skipping creation")
            
            # Create user_id index only if it doesn't exist
            if "user_id_1" not in existing_token_indexes:
                await tokens.create_index("user_id")
                logger.info("Created user_id index")
            else:
                logger.debug("User_id index already exists, skipping creation")
            
            # Create expires_at TTL index only if it doesn't exist
            if "expires_at_1" not in existing_token_indexes:
                await tokens.create_index("expires_at", expireAfterSeconds=0)
                logger.info("Created expires_at TTL index")
            else:
                logger.debug("Expires_at index already exists, skipping creation")
            
            logger.info("MongoDB indexes verified")
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")

    
    async def get_collection(self, collection_name: str):
        """Get a MongoDB collection, ensuring it exists first."""
        if self.db is None:
            logger.error("MongoDB database not initialized")
            return None
            
        # Ensure collection exists
        # await self._ensure_collection_exists(collection_name) # Too noisy to log every check
        return self.db[collection_name]
    
    async def get_users_collection(self):
        """Get the collection that stores user data (property_data)."""
        return await self.get_collection(settings.MONGODB_COLLECTION_NAME)
    
    async def get_property_data_collection(self):
        """Get the property_data collection."""
        return await self.get_collection(settings.MONGODB_COLLECTION_NAME)

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
