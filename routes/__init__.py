"""
Routes module - centralized route registration for the FastAPI application.
"""

from routes.auth_routes import setup_auth_routes
from routes.page_routes import setup_page_routes
from routes.api_routes import setup_api_routes


def setup_routes(app, static_dir: str):
    """
    Register all application routes with the FastAPI app.
    
    Args:
        app: FastAPI application instance
        static_dir: Path to static files directory
    """
    setup_auth_routes(app, static_dir)
    setup_page_routes(app, static_dir)
    setup_api_routes(app)
