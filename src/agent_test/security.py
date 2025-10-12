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


async def validate_twilio_request(request: Request) -> bool:
    """
    Validate that the request comes from Twilio using request signature validation.

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

    # Get the full URL that Twilio called
    url = str(request.url)

    # Get the Twilio signature from headers
    signature = request.headers.get("X-Twilio-Signature", "")

    # Get form data
    form_data = await request.form()
    params = dict(form_data)

    # Validate the request
    is_valid = validator.validate(url, params, signature)

    if not is_valid:
        logger.warning(f"Invalid Twilio signature from {get_client_ip(request)}")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    logger.debug("Twilio signature validated successfully")
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
