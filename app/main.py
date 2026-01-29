from app.route import setup_routes
from fastapi import FastAPI
from app.middleware import setup_middlewares
from app.config import settings
from app.logger import setup_logger

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

# Setup logger
setup_logger(settings)

# Attach config to the app instance
app.state.config = settings

# Apply all middlewares first
setup_middlewares(app)

# Then setup routes
setup_routes(app)