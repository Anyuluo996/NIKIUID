"""Crypto helpers for Passport and MYL requests."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime

from Crypto.Cipher import AES


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    """Apply PKCS7 padding."""
    padding_len = block_size - (len(data) % block_size)
    return data + bytes([padding_len] * padding_len)


def _pkcs7_unpad(data: bytes) -> bytes:
    """Remove PKCS7 padding."""
    padding_len = data[-1]
    return data[:-padding_len]


def aes_encrypt(plaintext: str, key: str) -> str:
    """Encrypt payloads the same way as the web login page."""
    key_bytes = key.encode("utf-8")[:16]
    iv = key_bytes
    cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
    padded = _pkcs7_pad(plaintext.encode("utf-8"))
    encrypted_bytes = cipher.encrypt(padded)
    return base64.b64encode(encrypted_bytes).decode()


def aes_decrypt(ciphertext: str, key: str) -> str:
    """Decrypt payloads produced by the web login page."""
    key_bytes = key.encode("utf-8")[:16]
    iv = key_bytes
    encrypted_bytes = base64.b64decode(ciphertext)
    cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(encrypted_bytes)
    return _pkcs7_unpad(decrypted).decode("utf-8")


def generate_device_id() -> str:
    """Generate the base device id used by the current web flow."""
    return str(uuid.uuid4())


def generate_doid() -> str:
    """Generate a Passport DOID that matches the observed web format."""
    return f"fe-{uuid.uuid4().hex}"


def generate_web_deviceid(device_id: str | None = None) -> str:
    """Generate the Passport web_deviceid observed in the browser flow."""
    base_device_id = device_id or generate_device_id()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
    return f"{base_device_id}-{timestamp}"
