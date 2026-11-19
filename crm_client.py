"""Подписанный HTTP-клиент пилотной интеграции с CRM."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import aiohttp

from config import (
    CRM_API_SECRET,
    CRM_API_TIMEOUT_SECONDS,
    CRM_API_URL,
    CRM_API_VERIFY_SSL,
)


class CrmIntegrationError(RuntimeError):
    """Безопасная для показа оператору ошибка интеграции."""


class CrmClient:
    def __init__(self) -> None:
        self.url = CRM_API_URL
        self.secret = CRM_API_SECRET
        self.verify_ssl = CRM_API_VERIFY_SSL
        self.timeout = aiohttp.ClientTimeout(total=CRM_API_TIMEOUT_SECONDS)

    @property
    def configured(self) -> bool:
        return bool(self.url and self.secret)

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise CrmIntegrationError("Интеграция с CRM не настроена")

        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = hmac.new(
            self.secret.encode("utf-8"),
            timestamp.encode("ascii") + b"\n" + body,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Helpdesk-Timestamp": timestamp,
            "X-Helpdesk-Signature": signature,
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.url,
                    data=body,
                    headers=headers,
                    ssl=self.verify_ssl,
                ) as response:
                    try:
                        result = await response.json(content_type=None)
                    except Exception as exc:
                        raise CrmIntegrationError(
                            f"CRM вернула некорректный ответ (HTTP {response.status})"
                        ) from exc
        except CrmIntegrationError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise CrmIntegrationError("CRM временно недоступна") from exc

        if response.status >= 400 or not isinstance(result, dict) or not result.get("ok"):
            message = result.get("error") if isinstance(result, dict) else None
            raise CrmIntegrationError(str(message or f"Ошибка CRM (HTTP {response.status})"))
        if not isinstance(result.get("task_id"), int):
            raise CrmIntegrationError("CRM не вернула номер созданной задачи")
        return result
