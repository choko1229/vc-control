from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet


class SecretBox:
    def __init__(self, key_path: Path) -> None:
        self.key_path = key_path
        self._fernet = Fernet(self._ensure_key())

    def _ensure_key(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
        return self.key_path.read_bytes().strip()

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str | None) -> str | None:
        if not token:
            return None
        return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
