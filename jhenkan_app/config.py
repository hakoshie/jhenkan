from __future__ import annotations

import json
import os
import sys
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path

import keyring


APP_NAME = "JHenkan"
KEYRING_USER = "default"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PROVIDERS = ("gemini", "openai")
KEYRING_SERVICES = {
    "openai": "JHenkan OpenAI API",
    "gemini": "JHenkan Gemini API",
}
KEY_ENVIRONMENTS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def data_dir() -> Path:
    base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / APP_NAME


def config_path() -> Path:
    return data_dir() / "settings.json"


@dataclass
class Settings:
    provider: str = "gemini"
    openai_model: str = "gpt-5.6-luna"
    gemini_model: str = "gemini-3.6-flash"
    hotkey: str = "ctrl+j"
    start_with_windows: bool = True
    api_timeout_seconds: float = 30.0

    @classmethod
    def load(cls) -> "Settings":
        try:
            values = json.loads(config_path().read_text(encoding="utf-8"))
            if "model" in values and "openai_model" not in values:
                values["openai_model"] = values["model"]
            allowed = cls.__dataclass_fields__.keys()
            settings = cls(**{key: value for key, value in values.items() if key in allowed})
            if settings.provider not in PROVIDERS:
                settings.provider = "gemini"
            return settings
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return cls()

    def save(self) -> None:
        data_dir().mkdir(parents=True, exist_ok=True)
        config_path().write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @property
    def model(self) -> str:
        return self.gemini_model if self.provider == "gemini" else self.openai_model


def get_api_key(provider: str) -> str:
    if provider not in PROVIDERS:
        return ""
    return keyring.get_password(KEYRING_SERVICES[provider], KEYRING_USER) or os.getenv(
        KEY_ENVIRONMENTS[provider], ""
    )


def set_api_key(provider: str, value: str) -> None:
    if value:
        keyring.set_password(KEYRING_SERVICES[provider], KEYRING_USER, value)


def startup_command() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "python.exe":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
    app = Path(__file__).resolve().parents[1] / "app.pyw"
    return f'"{executable}" "{app}"'


def startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False


def set_startup(enabled: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
