"""Tests for FieldEncryptor (credential encryption at rest)."""

import pytest
from cryptography.fernet import InvalidToken

from niles.crypto import FieldEncryptor, _PREFIX


class TestFieldEncryptor:
    """Core encrypt/decrypt round-trip tests."""

    @pytest.fixture
    def enc(self):
        return FieldEncryptor(FieldEncryptor.generate_key())

    def test_roundtrip(self, enc):
        secret = "my-super-secret-token"
        encrypted = enc.encrypt(secret)
        assert encrypted != secret
        assert encrypted.startswith(_PREFIX)
        assert enc.decrypt(encrypted) == secret

    def test_roundtrip_unicode(self, enc):
        secret = "Passwort mit Ümlauten: äöüß"
        assert enc.decrypt(enc.encrypt(secret)) == secret

    def test_empty_string_passthrough(self, enc):
        assert enc.encrypt("") == ""
        assert enc.decrypt("") == ""

    def test_none_passthrough(self, enc):
        assert enc.encrypt(None) is None
        assert enc.decrypt(None) is None

    def test_plaintext_fallback(self, enc):
        """Values without v1: prefix are returned as-is (backward compat)."""
        plaintext = "legacy-unencrypted-token"
        assert enc.decrypt(plaintext) == plaintext

    def test_wrong_key_raises(self):
        enc1 = FieldEncryptor(FieldEncryptor.generate_key())
        enc2 = FieldEncryptor(FieldEncryptor.generate_key())
        encrypted = enc1.encrypt("secret")
        with pytest.raises(InvalidToken):
            enc2.decrypt(encrypted)

    def test_corrupted_ciphertext_raises(self, enc):
        with pytest.raises(InvalidToken):
            enc.decrypt(f"{_PREFIX}not-a-valid-fernet-token")

    def test_generate_key_format(self):
        key = FieldEncryptor.generate_key()
        assert isinstance(key, str)
        assert len(key) == 44  # Fernet key is 32 bytes -> 44 chars base64

    def test_different_encryptions_differ(self, enc):
        """Same plaintext encrypted twice yields different ciphertexts (Fernet uses timestamps)."""
        a = enc.encrypt("same-input")
        b = enc.encrypt("same-input")
        assert a != b
        assert enc.decrypt(a) == enc.decrypt(b) == "same-input"
