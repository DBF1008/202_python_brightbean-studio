"""AES-256-GCM encrypted model fields.

Key is derived from SECRET_KEY via HKDF. Values are stored as
base64-encoded ciphertext with a 12-byte nonce prepended.
"""

import base64
import json
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)


def _derive_key() -> bytes:
    """Derive a 256-bit encryption key from SECRET_KEY via HKDF."""
    secret = settings.SECRET_KEY.encode("utf-8")
    salt = getattr(settings, "ENCRYPTION_KEY_SALT", None)
    if not salt:
        raise ValueError(
            "ENCRYPTION_KEY_SALT must be set. Generate a random value and add it "
            "to your environment variables. This is required for secure encryption."
        )
    if isinstance(salt, str):
        salt = salt.encode("utf-8")
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        info=b"brightbean-field-encryption",
    )
    return hkdf.derive(secret)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string and return base64-encoded nonce+ciphertext."""
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_value(encrypted: str) -> str:
    """Decrypt a base64-encoded nonce+ciphertext string."""
    key = _derive_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(encrypted)
    nonce = raw[:12]
    ciphertext = raw[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


class EncryptedTextField(models.TextField):
    """A TextField that encrypts its value at rest using AES-256-GCM."""

    def get_prep_value(self, value):
        if value is None:
            return None
        return encrypt_value(str(value))

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        try:
            return decrypt_value(value)
        except (InvalidTag, ValueError, base64.binascii.Error) as e:
            logger.error("Failed to decrypt EncryptedTextField: %s", e)
            raise ValueError("Decryption failed - possibly wrong SECRET_KEY or corrupted data") from e

    def to_python(self, value):
        return value


class EncryptedJSONField(models.TextField):
    """A field that stores JSON data encrypted at rest using AES-256-GCM."""

    def get_prep_value(self, value):
        if value is None:
            return None
        return encrypt_value(json.dumps(value))

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        try:
            return json.loads(decrypt_value(value))
        except (InvalidTag, ValueError, base64.binascii.Error) as e:
            logger.error("Failed to decrypt EncryptedJSONField: %s", e)
            raise ValueError("Decryption failed - possibly wrong SECRET_KEY or corrupted data") from e

    def to_python(self, value):
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                # Value is likely already-encrypted ciphertext from the DB,
                # which will be handled by from_db_value. Return as-is.
                return value
        return value
