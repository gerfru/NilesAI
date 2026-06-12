"""Application-layer field encryption for sensitive database columns.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the ``cryptography`` package.
Ciphertexts are prefixed with ``v1:`` to support future key rotation
without re-encrypting all rows immediately.
"""

from cryptography.fernet import Fernet

_KEY_VERSION = "v1"
_PREFIX = f"{_KEY_VERSION}:"


class FieldEncryptor:
    """Encrypt/decrypt individual field values for database storage.

    Currently single-key only.  Changing CREDENTIAL_ENCRYPTION_KEY makes
    all existing encrypted values unreadable — there is no MultiFernet
    key-rotation support yet.  The ``v1:`` prefix is reserved for a
    future migration to multi-key decryption.

    Usage::

        encryptor = FieldEncryptor(key)
        encrypted = encryptor.encrypt("my-secret")   # "v1:gAAA..."
        plain     = encryptor.decrypt(encrypted)      # "my-secret"
        plain     = encryptor.decrypt("legacy-plain") # "legacy-plain" (fallback)
    """

    def __init__(self, key: str):
        """Initialise with a Fernet key (32-byte URL-safe base64 string).

        Generate one via ``FieldEncryptor.generate_key()``.
        """
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string for DB storage.

        Returns versioned ciphertext (``v1:<token>``).
        Empty/None values pass through unchanged.
        """
        if not plaintext:
            return plaintext
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return f"{_PREFIX}{token.decode('ascii')}"

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a versioned ciphertext from the database.

        If the value lacks the version prefix, it is returned as-is
        (backward compatibility with pre-encryption plaintext data).

        Raises ``cryptography.fernet.InvalidToken`` if the prefix is
        present but decryption fails (wrong key or corrupted data).
        """
        if not ciphertext:
            return ciphertext
        if not ciphertext.startswith(_PREFIX):
            return ciphertext  # legacy plaintext — transparent fallback
        token = ciphertext[len(_PREFIX) :]
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")

    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet key suitable for ``CREDENTIAL_ENCRYPTION_KEY``."""
        return Fernet.generate_key().decode("ascii")
