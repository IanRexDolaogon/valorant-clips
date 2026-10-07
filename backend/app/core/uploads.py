"""Bound video request bodies before routing, including chunked HTTP requests."""
from fastapi.responses import JSONResponse

from app.core.config import settings


class UploadLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/videos") or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        limit = settings.max_upload_bytes
        headers = dict(scope["headers"])
        try:
            oversized = int(headers.get(b"content-length", b"0")) > limit
        except ValueError:
            return await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
        body = bytearray()
        while not oversized:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            piece = message.get("body", b"")
            oversized = len(body) + len(piece) > limit
            if not oversized:
                body.extend(piece)
            if not message.get("more_body", False):
                break
        if oversized:
            return await JSONResponse({"detail": "Video upload exceeds 10 MB limit"}, status_code=413)(scope, receive, send)
        async def bounded_body():
            return {"type": "http.request", "body": bytes(body), "more_body": False}
        await self.app(scope, bounded_body, send)
