"""
Authentication routes - login, logout, and login page.
"""

import logging
import os

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from auth import authenticate_user, create_token, LoginRateLimiter

logger = logging.getLogger(__name__)


def setup_auth_routes(app, static_dir: str):
    """Register authentication routes with the FastAPI app."""

    @app.get("/login")
    async def login_page():
        """Serve login page."""
        login_file = os.path.join(static_dir, "login.html")
        if os.path.exists(login_file):
            return FileResponse(login_file, media_type="text/html")
        return HTMLResponse("<h1>Login page not found</h1>", status_code=404)

    @app.post("/api/login")
    async def login_api(request: Request):
        """Authenticate and return JWT token with rate limiting."""
        # Get client IP
        client_ip = request.client.host if request.client else "unknown"

        # Check rate limit
        allowed, lockout_msg = LoginRateLimiter.check(client_ip)
        if not allowed:
            raise HTTPException(status_code=429, detail=lockout_msg)

        try:
            body = await request.json()
            username = body.get("username", "")
            password = body.get("password", "")

            if authenticate_user(username, password):
                LoginRateLimiter.reset(client_ip)
                token = create_token(username)
                response = JSONResponse({"token": token, "username": username})
                response.set_cookie(
                    key="access_token",
                    value=token,
                    path="/",
                    httponly=True,
                    samesite="strict",
                    max_age=86400,  # 24 hours, matches JWT expiry
                )
                return response
            else:
                remaining, is_locked = LoginRateLimiter.record_failure(client_ip)
                if is_locked:
                    raise HTTPException(
                        status_code=429,
                        detail="5 başarısız deneme! Hesap 24 saat kilitlendi."
                    )
                raise HTTPException(
                    status_code=401,
                    detail=f"Hatalı kullanıcı adı veya şifre. Kalan deneme: {remaining}"
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Login error: {e}", exc_info=True)
            return {"status": "error", "message": "Internal Server Error"}

    @app.post("/api/logout")
    async def logout_api():
        """Clear the HttpOnly auth cookie."""
        response = JSONResponse({"status": "ok"})
        response.delete_cookie(key="access_token", path="/")
        return response
