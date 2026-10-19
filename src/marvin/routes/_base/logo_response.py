"""Serving a provider logo (services/integrations/logos.py validated it): integrations' and AI providers' alike."""

from fastapi import HTTPException, Request, Response, status


def _logo_headers(logo) -> dict[str, str]:
    return {
        "ETag": logo.etag,
        "Cache-Control": "public, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        # The logo is ours to serve but not ours to trust: nothing in it may load, run or navigate,
        # even when opened directly rather than through <img>.
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    }


def logo_response(logo, request: Request) -> Response:
    """The logo with locked-down headers (304 on a matching ETag); 404 when there is none."""
    if logo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No logo.")
    headers = _logo_headers(logo)
    if logo.etag in [tag.strip() for tag in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=logo.data, media_type=logo.content_type, headers=headers)
