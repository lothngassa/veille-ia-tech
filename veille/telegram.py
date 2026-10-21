"""Client Telegram minimal (API Bot, HTTPS + JSON, bibliothèque standard)."""

from __future__ import annotations

import html
import json
import logging
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    def __init__(self, message: str, code: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


def call(token: str, method: str, params: dict | None = None, timeout: float = 30) -> dict | list | bool:
    req = urllib.request.Request(
        API_URL.format(token=token, method=method),
        data=json.dumps(params or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            raise TelegramError(f"HTTP {e.code}", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # Ne jamais inclure l'URL : elle contient le token.
        reason = getattr(e, "reason", e)
        raise TelegramError(f"réseau indisponible ({reason})") from None
    if not payload.get("ok"):
        params_ = payload.get("parameters") or {}
        raise TelegramError(payload.get("description", "erreur inconnue"), payload.get("error_code"),
                            params_.get("retry_after"))
    return payload["result"]


def get_me(token: str) -> dict:
    return call(token, "getMe")


def get_updates(token: str, offset: int | None = None, timeout: int = 0) -> list[dict]:
    params = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    return call(token, "getUpdates", params, timeout=timeout + 15)


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def send_message(token: str, chat_id: str | int, text: str, silent: bool = False, attempts: int = 4) -> None:
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "disable_notification": silent,
    }
    for attempt in range(1, attempts + 1):
        try:
            call(token, "sendMessage", params)
            return
        except TelegramError as e:
            if e.code == 429 and attempt < attempts:
                time.sleep((e.retry_after or 5) + 1)
                continue
            if e.code == 400 and "parse" in str(e).lower() and params.get("parse_mode"):
                # Mise en forme refusée : on envoie le même contenu en texte brut plutôt que rien.
                log.warning("Telegram refuse la mise en forme (%s) : envoi en texte brut", e)
                params = {**params, "text": _strip_html(text)}
                params.pop("parse_mode")
                continue
            if e.code is None and attempt < attempts:  # coupure réseau
                time.sleep(5 * attempt)
                continue
            raise


def send_messages(token: str, chat_id: str | int, messages: list[str]) -> None:
    """Envoie une série de messages. Seul le premier fait sonner le téléphone."""
    for i, text in enumerate(messages):
        send_message(token, chat_id, text, silent=i > 0)
        if i < len(messages) - 1:
            time.sleep(0.6)
