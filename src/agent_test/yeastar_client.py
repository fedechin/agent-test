"""
Yeastar P-Series PBX API client for messaging integration.
Handles authentication, sending messages, and transferring sessions.
"""
import os
import time
import logging
import httpx
from typing import Optional

logger = logging.getLogger("rag_agent")

# API path for Yeastar P-Series
API_PATH = "/openapi/v1.0"

# Yeastar rechaza cuerpos de mensaje de más de 1600 caracteres (errcode 40002,
# validación 'lte' 1600). Usamos un tope algo menor como margen y, si el mensaje
# lo supera, lo dividimos en varias partes que se envían en orden. Es una red de
# seguridad: aunque el modelo se pase de largo, el envío nunca falla.
MAX_MSG_LEN = 1500


def split_message(text: str, limit: int = MAX_MSG_LEN) -> list:
    """Divide un mensaje en partes de a lo sumo `limit` caracteres, cortando en
    límites de párrafo (\\n\\n) o línea, y solo por palabras como último recurso,
    para no partir palabras al medio."""
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []

    # 1) Descomponer en segmentos "atómicos" que ya quepan en el límite.
    segments = []
    for para in text.split("\n\n"):
        if len(para) <= limit:
            segments.append(para)
            continue
        for line in para.split("\n"):
            if len(line) <= limit:
                segments.append(line)
                continue
            cur = ""
            for word in line.split(" "):
                cand = (cur + " " + word).strip()
                if len(cand) <= limit:
                    cur = cand
                else:
                    if cur:
                        segments.append(cur)
                    cur = word[:limit]  # palabra más larga que el límite: corte duro
            if cur:
                segments.append(cur)

    # 2) Reempaquetar los segmentos respetando el límite.
    parts = []
    cur = ""
    for seg in segments:
        sep = "\n\n" if cur else ""
        if len(cur) + len(sep) + len(seg) <= limit:
            cur += sep + seg
        else:
            if cur:
                parts.append(cur)
            cur = seg
    if cur:
        parts.append(cur)
    return parts


class YeastarClient:
    """Client for interacting with the Yeastar P-Series PBX API."""

    def __init__(self):
        self.base_url = os.getenv("YEASTAR_BASE_URL", "").rstrip("/")
        self.client_id = os.getenv("YEASTAR_CLIENT_ID", "")
        self.client_secret = os.getenv("YEASTAR_CLIENT_SECRET", "")
        self.webhook_secret = os.getenv("YEASTAR_WEBHOOK_SECRET", "")
        self.transfer_destination_type = os.getenv("YEASTAR_TRANSFER_DEST_TYPE", "queue")
        try:
            self.transfer_destination_id = int(os.getenv("YEASTAR_TRANSFER_DEST_ID", "0"))
        except (ValueError, TypeError):
            self.transfer_destination_id = 0
            logger.warning("YEASTAR_TRANSFER_DEST_ID is not a valid number, defaulting to 0")

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._refresh_token: Optional[str] = None
        self._refresh_expires_at: float = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.client_id and self.client_secret)

    def _api_url(self, endpoint: str) -> str:
        return f"{self.base_url}{API_PATH}/{endpoint}"

    async def _get_token(self) -> str:
        """Get or refresh the API access token."""
        now = time.time()

        # Return cached token if still valid (with 60s margin)
        if self._access_token and now < (self._token_expires_at - 60):
            return self._access_token

        # Try refresh token first
        if self._refresh_token and now < (self._refresh_expires_at - 60):
            return await self._refresh_access_token()

        # Full authentication
        return await self._authenticate()

    async def _authenticate(self) -> str:
        """Authenticate with client credentials and get access token."""
        url = self._api_url("get_token")
        logger.info(f"Yeastar auth: calling {url}")
        payload = {
            "username": self.client_id,
            "password": self.client_secret
        }

        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "OpenAPI"
                }
            )
            logger.info(f"Yeastar auth response: status={response.status_code}, body={response.text[:300]}")
            data = response.json()

        if data.get("errcode") != 0:
            logger.error(f"Yeastar auth failed: {data}")
            raise Exception(f"Yeastar authentication failed: {data.get('errmsg')}")

        now = time.time()
        self._access_token = data["access_token"]
        self._token_expires_at = now + data.get("access_token_expire_time", 1800)
        self._refresh_token = data.get("refresh_token")
        self._refresh_expires_at = now + data.get("refresh_token_expire_time", 86400)

        logger.info("Yeastar API authenticated successfully")
        return self._access_token

    async def _refresh_access_token(self) -> str:
        """Refresh the access token using the refresh token."""
        url = self._api_url("refresh_token")
        payload = {"refresh_token": self._refresh_token}

        try:
            async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "OpenAPI"
                    }
                )
                data = response.json()

            if data.get("errcode") != 0:
                logger.warning("Yeastar token refresh failed, re-authenticating")
                return await self._authenticate()

            now = time.time()
            self._access_token = data["access_token"]
            self._token_expires_at = now + data.get("access_token_expire_time", 1800)
            self._refresh_token = data.get("refresh_token", self._refresh_token)
            self._refresh_expires_at = now + data.get("refresh_token_expire_time", 86400)

            logger.debug("Yeastar token refreshed successfully")
            return self._access_token

        except Exception as e:
            logger.warning(f"Yeastar token refresh error: {e}, re-authenticating")
            return await self._authenticate()

    async def send_message(self, session_id: int, message_body: str) -> dict:
        """
        Send a text message in an existing session.

        Si el mensaje supera el límite de Yeastar (MAX_MSG_LEN), se divide en
        varias partes que se envían en orden. Devuelve la respuesta del último
        envío. Si alguna parte falla, se propaga la excepción.

        Args:
            session_id: The Yeastar message session ID.
            message_body: The text message to send.

        Returns:
            API response dict with errcode, msg_id, session_id.
        """
        parts = split_message(message_body)
        if len(parts) > 1:
            logger.info(
                f"Yeastar message split into {len(parts)} parts "
                f"(session={session_id}, len={len(message_body)})"
            )

        data = None
        for part in parts:
            data = await self._send_one(session_id, part)
        return data

    async def _send_one(self, session_id: int, message_body: str) -> dict:
        """Envía un único mensaje (una parte) a la sesión."""
        token = await self._get_token()
        url = self._api_url(f"message/send?access_token={token}")

        payload = {
            "sender_type": 9,  # Third-party platform
            "session_id": session_id,
            "msg_kind": 0,  # Normal message
            "msg_type": 0,  # User message
            "msg_body": message_body
        }

        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "OpenAPI"
                }
            )
            data = response.json()

        if data.get("errcode") != 0:
            logger.error(f"Yeastar send_message failed: {data}")
            raise Exception(f"Yeastar send_message failed: {data.get('errmsg')}")

        logger.info(f"Yeastar message sent: session={session_id}, msg_id={data.get('msg_id')}")
        return data

    async def transfer_session(self, session_id: int,
                               destination_type: Optional[str] = None,
                               destination_id: Optional[int] = None) -> dict:
        """
        Transfer a message session to a queue or extension.

        Args:
            session_id: The Yeastar message session ID.
            destination_type: "queue", "extension", or "api". Defaults to env config.
            destination_id: The ID of the destination. Defaults to env config.

        Returns:
            API response dict.
        """
        token = await self._get_token()
        url = self._api_url(f"message_session/transfer?access_token={token}")

        dest_type = destination_type or self.transfer_destination_type
        dest_id = destination_id if destination_id is not None else self.transfer_destination_id

        payload = {
            "session_id": session_id,
            "destination_type": dest_type,
            "destination_id": dest_id
        }

        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "OpenAPI"
                }
            )
            data = response.json()

        if data.get("errcode") != 0:
            logger.error(f"Yeastar transfer failed: {data}")
            raise Exception(f"Yeastar transfer failed: {data.get('errmsg')}")

        logger.info(f"Yeastar session {session_id} transferred to {dest_type}:{dest_id}")
        return data

    def validate_webhook(self, token: Optional[str]) -> bool:
        """
        Validate webhook request using the shared secret token.
        If no secret is configured, all requests are accepted.
        """
        if not self.webhook_secret:
            return True
        return token == self.webhook_secret
