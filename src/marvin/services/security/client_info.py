"""Who is on the other end of a public request — the one place that knows about proxy headers.

The API sits behind Cloudflare (and a site's own server-side form proxy in front of that), so
``request.client.host`` is often the last hop, not the visitor. Precedence: the first
``X-Forwarded-For`` entry (what a well-behaved proxy sets, and what uvicorn already trusts via
``forwarded_allow_ips``), then Cloudflare's ``CF-Connecting-IP``, then the socket peer.
"""

from dataclasses import dataclass

from fastapi import Request

UNKNOWN_IP = "unknown"


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return UNKNOWN_IP


@dataclass(frozen=True)
class ClientInfo:
    """The submitter's network fingerprint, as far as the headers tell us."""

    ip_address: str
    user_agent: str | None
    referer: str | None

    @classmethod
    def from_request(cls, request: Request) -> "ClientInfo":
        return cls(
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            referer=request.headers.get("referer"),
        )

    def as_metadata(self) -> dict:
        return {"ip_address": self.ip_address, "user_agent": self.user_agent, "referer": self.referer}
