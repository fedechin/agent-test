"""
Security utilities for webhook validation and IP whitelisting.
"""
import os
from typing import Optional
from fastapi import Request, HTTPException
from twilio.request_validator import RequestValidator
import logging

logger = logging.getLogger("rag_agent")

# === Configuration ===
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_VALIDATE_REQUESTS = os.getenv("TWILIO_VALIDATE_REQUESTS", "true").lower() == "true"
ALLOWED_IPS = os.getenv("ALLOWED_IPS", "").split(",") if os.getenv("ALLOWED_IPS") else []

# Initialize Twilio validator if auth token is available
validator = RequestValidator(TWILIO_AUTH_TOKEN) if TWILIO_AUTH_TOKEN else None


def get_client_ip(request: Request) -> str:
    """
    Extract the client's real IP address from the request.
    Checks X-Forwarded-For header first (for proxies/load balancers), then falls back to client.host.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one (client IP)
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else "unknown"


def is_ip_whitelisted(ip: str) -> bool:
    """
    Check if the IP is in the whitelist.
    Returns True if no whitelist is configured (allowing all IPs).
    """
    if not ALLOWED_IPS or ALLOWED_IPS == [""]:
        # No whitelist configured, allow all IPs
        return True

    # Allow localhost for development
    if ip in ["127.0.0.1", "::1", "localhost"]:
        return True

    return ip in ALLOWED_IPS


def get_original_url(request: Request) -> str:
    """
    Reconstruct the original URL from proxy headers.

    When behind a proxy/load balancer (like Railway, nginx, etc.), the request URL
    that reaches the application is different from what the client originally called.
    This function reconstructs the original URL using proxy headers.

    Returns:
        The original URL that the client called, or the request URL if not behind a proxy.
    """
    # Check for proxy headers
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    forwarded_host = request.headers.get("X-Forwarded-Host")

    if forwarded_proto and forwarded_host:
        # Behind proxy - reconstruct original URL
        # Get the path and query string from the request
        path = request.url.path
        query = request.url.query

        # Build the original URL
        original_url = f"{forwarded_proto}://{forwarded_host}{path}"
        if query:
            original_url += f"?{query}"

        logger.debug(f"Reconstructed URL from proxy headers: {original_url}")
        return original_url

    # Not behind proxy - use request URL as-is
    return str(request.url)


async def validate_twilio_request(request: Request) -> bool:
    """
    Validate that the request comes from Twilio using request signature validation.

    Handles proxy environments (Railway, nginx, etc.) by reconstructing the original URL
    from X-Forwarded-* headers before validating the signature.

    Returns True if validation passes or is disabled.
    Raises HTTPException if validation fails.
    """
    # Skip validation if disabled
    if not TWILIO_VALIDATE_REQUESTS:
        logger.debug("Twilio request validation is disabled")
        return True

    # Skip validation if validator is not initialized
    if not validator:
        logger.warning("Twilio validator not initialized (missing TWILIO_AUTH_TOKEN)")
        return True

    # Get the original URL that Twilio called (handles proxy environments)
    url = get_original_url(request)

    # Get the Twilio signature from headers
    signature = request.headers.get("X-Twilio-Signature", "")

    # Get form data
    form_data = await request.form()
    params = dict(form_data)

    # Validate the request
    is_valid = validator.validate(url, params, signature)

    if not is_valid:
        logger.warning(f"Invalid Twilio signature from {get_client_ip(request)}")
        logger.debug(f"Validation URL: {url}")
        logger.debug(f"Signature: {signature}")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    logger.info(f"✅ Twilio signature validated successfully for {url}")
    return True


async def validate_ip_whitelist(request: Request) -> bool:
    """
    Validate that the request comes from an allowed IP address.

    Returns True if IP is whitelisted.
    Raises HTTPException if IP is not allowed.
    """
    client_ip = get_client_ip(request)

    if not is_ip_whitelisted(client_ip):
        logger.warning(f"Blocked request from non-whitelisted IP: {client_ip}")
        raise HTTPException(
            status_code=403,
            detail="Access denied: IP not whitelisted"
        )

    logger.debug(f"IP {client_ip} is whitelisted")
    return True


async def validate_webhook_request(request: Request) -> bool:
    """
    Perform all security validations on the webhook request.

    Validates:
    1. IP whitelist (if configured)
    2. Twilio signature (if enabled)

    Returns True if all validations pass.
    Raises HTTPException if any validation fails.
    """
    # Check IP whitelist first (faster check)
    await validate_ip_whitelist(request)

    # Then validate Twilio signature
    await validate_twilio_request(request)

    return True
