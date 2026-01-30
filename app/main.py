from app.route import setup_routes
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.middleware import setup_middlewares
from app.config import settings
from app.logger import setup_logger
from app.services.mongo_service import get_mongo_service
from loguru import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up...")
    mongo = await get_mongo_service()
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    if mongo:
        mongo.close()

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)

# Setup logger
setup_logger(settings)

# Attach config to the app instance
app.state.config = settings

# Apply all middlewares first
setup_middlewares(app)

# Then setup routes
setup_routes(app)