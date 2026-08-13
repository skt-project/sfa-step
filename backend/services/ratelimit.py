"""
Rate-limit key function that resolves the real client IP.

slowapi's default get_remote_address uses request.client.host — behind Cloud Run /
Vercel that is the *platform front-end*, so every user shares one key and the
limiter throttles everyone together (or effectively not at all). The platform
appends the originating client IP as the first entry of X-Forwarded-For, so we key
on that instead, falling back to the socket peer when the header is absent.
"""
from slowapi.util import get_remote_address
from starlette.requests import Request


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return get_remote_address(request)
