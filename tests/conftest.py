from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from jwt.algorithms import RSAAlgorithm
from jwt import PyJWKClient

from tests.constants import AUDIENCE, ISSUER, KID

__all__ = ["AUDIENCE", "ISSUER", "KID"]


@pytest.fixture(scope="session")
def rsa_private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def rsa_public_key(rsa_private_key):
    return rsa_private_key.public_key()


@pytest.fixture(scope="session")
def jwks_data(rsa_public_key):
    """JWK Set JSON built from the test RSA public key."""
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(rsa_public_key))
    jwk_dict["kid"] = KID
    jwk_dict["use"] = "sig"
    return {"keys": [jwk_dict]}


@pytest.fixture()
def make_jwt(rsa_private_key):
    """Factory: make_jwt(overrides) -> signed JWT string."""
    def _make(overrides: dict | None = None, kid: str = KID) -> str:
        payload = {
            "sub": "user-sub-123",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "email": "alice@gmail.com",
            "name": "Alice Wanjiku",
            "given_name": "Alice",
            "family_name": "Wanjiku",
            "realm_access": {"roles": ["user"]},
            "resource_access": {AUDIENCE: {"roles": ["read"]}},
            "organization": {
                "jkuat": {"id": "org-jkuat-id", "groups": ["/clubs/Robotics Club"]},
            },
        }
        if overrides:
            payload.update(overrides)
        pem = rsa_private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
        return jwt.encode(payload, pem, algorithm="RS256", headers={"kid": kid})
    return _make


@pytest.fixture()
def fake_jwks_client(rsa_public_key):
    """Fake PyJWKClient that always returns the test RSA public key.

    Inject this into TokenValidator instead of mocking the JWKS HTTP endpoint.
    """
    mock_key = MagicMock()
    mock_key.key = rsa_public_key

    client = MagicMock(spec=PyJWKClient)
    client.get_signing_key_from_jwt.return_value = mock_key
    return client


@pytest.fixture()
def amt_env():
    return {
        "AMT_KEYCLOAK_URL": "http://localhost:8080",
        "AMT_REALM": "amilliontechies",
        "AMT_CLIENT_ID": AUDIENCE,
        "AMT_CLIENT_SECRET": "test-secret",
    }
