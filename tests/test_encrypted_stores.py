"""Round-trip encryption tests for VikunjaCredentialStore and SettingsStore.

The default conftest disables encryption (CREDENTIAL_ENCRYPTION_KEY="").
These tests exercise the real Fernet encryption path to ensure write → read
produces the original plaintext.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from niles.crypto import FieldEncryptor
from niles.settings_store import SettingsStore
from niles.vikunja_store import VikunjaCredentialStore


@pytest.fixture
def encryptor():
    """FieldEncryptor with a real Fernet key."""
    return FieldEncryptor(Fernet.generate_key().decode())


@pytest.fixture
def mock_pool():
    """Minimal asyncpg pool mock with execute/fetch/fetchrow helpers."""
    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)

    # Simulate pool.acquire() → conn context manager
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.transaction = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))
    pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock()))
    pool._conn = conn  # expose for assertions
    return pool


# ---------------------------------------------------------------------------
# FieldEncryptor unit tests
# ---------------------------------------------------------------------------


class TestFieldEncryptor:
    def test_round_trip(self, encryptor):
        """encrypt → decrypt returns original plaintext."""
        plaintext = "super-secret-token-12345"
        encrypted = encryptor.encrypt(plaintext)
        assert encrypted.startswith("v1:")
        assert encryptor.decrypt(encrypted) == plaintext

    def test_empty_passthrough(self, encryptor):
        """Empty strings pass through unchanged."""
        assert encryptor.encrypt("") == ""
        assert encryptor.decrypt("") == ""

    def test_none_passthrough(self, encryptor):
        """None values pass through unchanged."""
        assert encryptor.encrypt(None) is None
        assert encryptor.decrypt(None) is None

    def test_legacy_plaintext_fallback(self, encryptor):
        """Values without v1: prefix are returned as-is (backward compat)."""
        assert encryptor.decrypt("old-plaintext-token") == "old-plaintext-token"

    def test_wrong_key_raises(self):
        """Decrypting with wrong key raises InvalidToken."""
        from cryptography.fernet import InvalidToken

        enc_a = FieldEncryptor(Fernet.generate_key().decode())
        enc_b = FieldEncryptor(Fernet.generate_key().decode())

        encrypted = enc_a.encrypt("secret")
        with pytest.raises(InvalidToken):
            enc_b.decrypt(encrypted)

    def test_generate_key(self):
        """generate_key produces a valid Fernet key."""
        key = FieldEncryptor.generate_key()
        # Should not raise
        enc = FieldEncryptor(key)
        assert enc.decrypt(enc.encrypt("test")) == "test"


# ---------------------------------------------------------------------------
# VikunjaCredentialStore with encryption
# ---------------------------------------------------------------------------


class TestVikunjaCredentialStoreEncrypted:
    async def test_upsert_encrypts_token(self, mock_pool, encryptor):
        """upsert_credentials stores encrypted token."""
        store = VikunjaCredentialStore(mock_pool, encryptor=encryptor)
        await store.upsert_credentials(user_id=1, api_token="my-vikunja-token", api_url="https://tasks.example.local")

        call_args = mock_pool.execute.call_args
        stored_token = call_args[0][2]  # $2 = encrypted token
        assert stored_token.startswith("v1:")
        assert stored_token != "my-vikunja-token"

    async def test_get_decrypts_token(self, mock_pool, encryptor):
        """get_credentials returns decrypted token."""
        encrypted_token = encryptor.encrypt("my-vikunja-token")

        mock_pool.fetchrow.return_value = {
            "user_id": 1,
            "api_token": encrypted_token,
            "api_url": "https://tasks.example.local",
            "password_synced": False,
        }

        store = VikunjaCredentialStore(mock_pool, encryptor=encryptor)
        creds = await store.get_credentials(user_id=1)

        assert creds is not None
        assert creds["api_token"] == "my-vikunja-token"

    async def test_round_trip(self, mock_pool, encryptor):
        """Write then read produces original plaintext."""
        store = VikunjaCredentialStore(mock_pool, encryptor=encryptor)

        # Write
        await store.upsert_credentials(user_id=1, api_token="round-trip-token", api_url="https://v.example.local")
        stored_token = mock_pool.execute.call_args[0][2]

        # Simulate read returning what was stored
        mock_pool.fetchrow.return_value = {
            "user_id": 1,
            "api_token": stored_token,
            "api_url": "https://v.example.local",
            "password_synced": False,
        }
        creds = await store.get_credentials(user_id=1)

        assert creds is not None
        assert creds["api_token"] == "round-trip-token"

    async def test_no_encryptor_stores_plaintext(self, mock_pool):
        """Without encryptor, token is stored as plaintext."""
        store = VikunjaCredentialStore(mock_pool, encryptor=None)
        await store.upsert_credentials(user_id=1, api_token="plain-token", api_url="")

        stored_token = mock_pool.execute.call_args[0][2]
        assert stored_token == "plain-token"


# ---------------------------------------------------------------------------
# SettingsStore with encryption
# ---------------------------------------------------------------------------


class TestSettingsStoreEncrypted:
    async def test_set_encrypts_sensitive_key(self, mock_pool, encryptor):
        """set() encrypts values for keys in _ENCRYPTED_KEYS."""
        store = SettingsStore(mock_pool, encryptor=encryptor)
        await store.set("notion_token", "ntn_secret_abc123")

        conn = mock_pool._conn
        call_args = conn.execute.call_args
        stored_json = call_args[0][2]  # $2 = json-serialised value
        stored_value = json.loads(stored_json)
        assert stored_value.startswith("v1:")
        assert stored_value != "ntn_secret_abc123"

    async def test_set_does_not_encrypt_normal_key(self, mock_pool, encryptor):
        """set() does NOT encrypt non-sensitive keys."""
        store = SettingsStore(mock_pool, encryptor=encryptor)
        await store.set("timezone", "Europe/Vienna")

        conn = mock_pool._conn
        call_args = conn.execute.call_args
        stored_json = call_args[0][2]
        stored_value = json.loads(stored_json)
        assert stored_value == "Europe/Vienna"

    async def test_get_all_decrypts_sensitive_key(self, mock_pool, encryptor):
        """get_all() decrypts values for keys in _ENCRYPTED_KEYS."""
        encrypted_token = encryptor.encrypt("ntn_secret_abc123")

        mock_pool.fetch.return_value = [
            {"key": "notion_token", "value": json.dumps(encrypted_token)},
            {"key": "timezone", "value": json.dumps("Europe/Vienna")},
        ]

        store = SettingsStore(mock_pool, encryptor=encryptor)
        result = await store.get_all()

        assert result["notion_token"] == "ntn_secret_abc123"
        assert result["timezone"] == "Europe/Vienna"

    async def test_round_trip_sensitive_key(self, mock_pool, encryptor):
        """Write then read of a sensitive key returns original plaintext."""
        store = SettingsStore(mock_pool, encryptor=encryptor)

        # Write
        await store.set("notion_token", "ntn_roundtrip_xyz")
        conn = mock_pool._conn
        stored_json = conn.execute.call_args[0][2]

        # Simulate read returning what was stored
        mock_pool.fetch.return_value = [
            {"key": "notion_token", "value": stored_json},
        ]
        result = await store.get_all()

        assert result["notion_token"] == "ntn_roundtrip_xyz"
