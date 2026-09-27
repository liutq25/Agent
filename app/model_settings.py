"""Local model preferences; API keys live in the OS credential vault."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import keyring
from pydantic import BaseModel, Field, field_validator

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "model_settings.json"
SERVICE = "CogniTutor-DS model API"
DEFAULT_URLS = {
    "openai_compatible": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}


class ModelSettings(BaseModel):
    protocol: str = "mock"
    model: str = ""
    base_url: str = ""
    timeout: int = Field(default=60, ge=5, le=180)

    @field_validator("protocol")
    @classmethod
    def valid_protocol(cls, value):
        if value not in ("mock", *DEFAULT_URLS):
            raise ValueError("Unsupported model protocol")
        return value

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid API base URL")
        if parsed.scheme == "http":
            try:
                if not ipaddress.ip_address(parsed.hostname).is_loopback:
                    raise ValueError("HTTP is allowed only for local loopback")
            except ValueError as error:
                if parsed.hostname != "localhost":
                    raise ValueError("Use HTTPS for remote API services") from error
        return value.rstrip("/")


def slot(settings: ModelSettings) -> str:
    data = f"{settings.protocol}|{settings.base_url}".encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:32]


def get_key(settings: ModelSettings) -> str:
    return keyring.get_password(SERVICE, slot(settings)) or ""


def delete_key(settings: ModelSettings):
    if get_key(settings):
        keyring.delete_password(SERVICE, slot(settings))


def load_settings() -> ModelSettings | None:
    if not SETTINGS_PATH.exists():
        return None
    return ModelSettings.model_validate(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))


def save_settings(settings: ModelSettings, key: str | None = None):
    if settings.protocol != "mock" and (not settings.model.strip() or not settings.base_url):
        raise ValueError("Model name and base URL are required")
    if key is not None and key.strip():
        keyring.set_password(SERVICE, slot(settings), key.strip())
    elif settings.protocol != "mock" and not get_key(settings):
        raise ValueError("API Key is required for this service address")
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_PATH.with_suffix(".tmp")
    temporary.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, SETTINGS_PATH)


def public_settings(settings: ModelSettings) -> dict:
    return {**settings.model_dump(), "has_key": bool(get_key(settings)) if settings.protocol != "mock" else False}
