"""Set the PWA administrator password without exposing it in shell history."""

from __future__ import annotations

import base64
import getpass
import hashlib
import os
import secrets
from pathlib import Path


ENV_PATH = Path("/opt/apex-crm/.env")
ITERATIONS = 600_000


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def update_env(encoded_password: str) -> None:
    original = ENV_PATH.stat()
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    replacement = f"PWA_PASSWORD_HASH={encoded_password}"
    updated: list[str] = []
    found = False
    for line in lines:
        if line.startswith("PWA_PASSWORD_HASH="):
            updated.append(replacement)
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(replacement)

    temporary = ENV_PATH.with_suffix(".env.tmp")
    temporary.write_text("\n".join(updated) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.chown(temporary, original.st_uid, original.st_gid)
    temporary.replace(ENV_PATH)


def main() -> None:
    password = getpass.getpass("Новый пароль PWA: ")
    confirmation = getpass.getpass("Повторите пароль: ")
    if password != confirmation:
        raise SystemExit("Пароли не совпадают.")
    if len(password) < 12:
        raise SystemExit("Пароль должен содержать не менее 12 символов.")

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    update_env(f"pbkdf2_sha256${ITERATIONS}${encode(salt)}${encode(digest)}")
    print("Пароль PWA сохранён.")


if __name__ == "__main__":
    main()
