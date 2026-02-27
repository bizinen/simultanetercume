"""
Page routes - serving HTML pages (admin, client-controls, root redirect).
"""

import os

from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

_BUSY_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Oturum Meşgul</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Inter', system-ui, sans-serif;
    background: #0a0a1a;
    color: #e0e0f0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .box {
    background: rgba(239,68,68,0.08);
    border: 1px solid rgba(239,68,68,0.25);
    border-radius: 20px;
    padding: 48px 56px;
    text-align: center;
    max-width: 440px;
  }
  .icon { font-size: 56px; margin-bottom: 20px; }
  h1 { font-size: 22px; font-weight: 700; color: #f87171; margin-bottom: 12px; }
  p { font-size: 14px; color: #8a8aaa; line-height: 1.6; margin-bottom: 28px; }
  .btn {
    display: inline-block;
    padding: 11px 28px;
    background: rgba(56,100,220,0.15);
    border: 1px solid rgba(56,100,220,0.3);
    border-radius: 10px;
    color: #7aa2f7;
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
    transition: all 0.2s;
  }
  .btn:hover { background: rgba(56,100,220,0.25); }
  .retry { margin-top: 12px; }
  .retry button {
    background: none; border: none; color: #5a5a7a;
    font-size: 13px; cursor: pointer; text-decoration: underline;
  }
</style>
<script>
  // Auto-refresh every 8 seconds to re-check session status
  setTimeout(function() { location.reload(); }, 8000);
</script>
</head>
<body>
  <div class="box">
    <div class="icon">🔴</div>
    <h1>Oturum Şu An Meşgul</h1>
    <p>Başka bir kullanıcı şu an çeviri sistemini test ediyor.<br>
       Oturum sona erdiğinde bu sayfa otomatik olarak yenilenecek.</p>
    <a href="/admin" class="btn">Admin Paneline Git</a>
    <div class="retry">
      <button onclick="location.reload()">Şimdi Yenile</button>
    </div>
  </div>
</body>
</html>"""


def setup_page_routes(app, static_dir: str):
    """Register page serving routes with the FastAPI app."""

    @app.get("/")
    async def root_redirect():
        """Redirect root to login page."""
        return RedirectResponse(url="/login")

    @app.get("/admin")
    async def admin_page():
        """Serve admin page (auth checked client-side via JS)."""
        admin_file = os.path.join(static_dir, "admin.html")
        if os.path.exists(admin_file):
            return FileResponse(admin_file, media_type="text/html")
        return HTMLResponse("<h1>Admin page not found</h1>", status_code=404)

    @app.get("/client-controls")
    async def client_with_controls():
        """Client page with controls panel — blocked if session is busy."""
        from routes.context import get_active_connection_count
        if get_active_connection_count() > 0:
            return HTMLResponse(_BUSY_HTML, status_code=200)
        client_control_file = os.path.join(static_dir, "client_control.html")
        if os.path.exists(client_control_file):
            return FileResponse(client_control_file, media_type="text/html")
        return HTMLResponse("<h1>Client control page not found</h1>", status_code=404)

