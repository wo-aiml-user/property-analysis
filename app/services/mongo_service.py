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
            # 1. User Collection
            await self._ensure_collection_exists(settings.MONGODB_USER_COLLECTION)
            user_col = self.db[settings.MONGODB_USER_COLLECTION]
            user_indexes = await user_col.index_information()
            
            if "email_1" not in user_indexes:
                await user_col.create_index("email", unique=True)
                logger.info("Created email index on prop_user_data")
            
            # Index for refresh token lookup
            if "refresh_tokens.token_hash_1" not in user_indexes:
                await user_col.create_index("refresh_tokens.token_hash")
                logger.info("Created refresh_tokens.token_hash index on prop_user_data")

            # 2. Property Collection
            await self._ensure_collection_exists(settings.MONGODB_PROPERTY_COLLECTION)
            prop_col = self.db[settings.MONGODB_PROPERTY_COLLECTION]
            prop_indexes = await prop_col.index_information()
            
            if "property_id_1" not in prop_indexes:
                await prop_col.create_index("property_id", unique=True)
                logger.info("Created property_id index on prop_property_data")
                
            if "user_id_1" not in prop_indexes:
                await prop_col.create_index("user_id")
                logger.info("Created user_id index on prop_property_data")

            # 3. Chat History Collection
            await self._ensure_collection_exists(settings.MONGODB_CHAT_COLLECTION)
            chat_col = self.db[settings.MONGODB_CHAT_COLLECTION]
            chat_indexes = await chat_col.index_information()
            
            if "property_id_1" not in chat_indexes:
                await chat_col.create_index("property_id", unique=True)
                logger.info("Created property_id index on prop_chat_history")
            
            logger.info("MongoDB indexes verified for all collections")
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
        """Get the users collection."""
        return await self.get_collection(settings.MONGODB_USER_COLLECTION)
    
    async def get_property_data_collection(self):
        """Get the properties collection."""
        return await self.get_collection(settings.MONGODB_PROPERTY_COLLECTION)

    async def get_chat_collection(self):
        """Get the chat history collection."""
        return await self.get_collection(settings.MONGODB_CHAT_COLLECTION)

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
