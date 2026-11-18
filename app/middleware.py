"""Bound request bodies before FastAPI parses them."""

from collections.abc import Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.i18n import message as translate_message


class RequestSizeLimitMiddleware:
    """Check both the declared length and the bytes actually received."""

    def __init__(
        self,
        app: ASGIApp,
        max_size: Callable[[], int],
        language: Callable[[], str] = lambda: "en",
    ) -> None:
        self.app = app
        self.max_size = max_size
        self.language = language

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_response(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = dict(message)
                headers = list(message.get("headers", []))
                headers.append((b"content-language", self.language().encode("ascii")))
                if scope["path"].startswith("/api/"):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        if scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send_response)
            return

        limit = self.max_size()
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None:
            try:
                declared = int(length)
                if declared < 0:
                    raise ValueError("Negative Content-Length")
            except ValueError:
                response = JSONResponse(
                    {
                        "detail": translate_message(
                            self.language(), "err_content_length"
                        )
                    },
                    status_code=400,
                )
                await response(scope, receive, send_response)
                return
            if declared > limit:
                await self.reject(scope, receive, send_response, limit)
                return

        # Buffer at most `limit` bytes; never trust Content-Length alone. The
        # server owns each incoming chunk, which is inspected before copying it.
        buffer = bytearray()
        received = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            received += len(chunk)
            if received > limit:
                await self.reject(scope, receive, send_response, limit)
                return
            buffer.extend(chunk)
            if not message.get("more_body", False):
                break

        body = bytes(buffer)
        del buffer
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send_response)

    async def reject(
        self, scope: Scope, receive: Receive, send: Send, limit: int
    ) -> None:
        response = JSONResponse(
            {
                "detail": translate_message(
                    self.language(), "err_request_too_large", limit=limit
                )
            },
            status_code=413,
        )
        await response(scope, receive, send)
