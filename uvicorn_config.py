import os
import uvicorn
import multiprocessing
from app.config import settings  # Import your FastAPI settings

ENV = settings.ENVIRONMENT.lower()

if ENV == "development":
    reload = True
    log_level = "debug"
    workers = 1
elif ENV == "production":
    reload = False
    log_level = "warning"
    workers = multiprocessing.cpu_count() * 2 + 1
else:
    raise ValueError(f"Unknown APP_ENV: {ENV}")

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",  # Replace with your actual FastAPI app import
        host=settings.HOST,
        port=settings.PORT,
        reload=reload,
        workers=workers,
        log_level=log_level
    )