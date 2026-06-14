"""Unit tests for app.apns + app.notify.ApnsNotifier (Epic 8 delivery).

No real network/APNs — JWT signing uses a generated test EC P-256 key, and
`ApnsNotifier.send` is exercised against a fake `ApnsTransport`.
"""

from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.apns import APNS_PROD_HOST, APNS_SANDBOX_HOST, ApnsClient, ApnsResult, ApnsTokenSigner
from app.notify import ApnsNotifier, NoOpNotifier, get_notifier


@pytest.fixture(scope="module")
def test_ec_key_pem() -> str:
    """A freshly generated EC P-256 private key in PEM (NOT the real .p8)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


class FakeApnsTransport:
    """Records every POST instead of hitting the network.

    `failures` is a set of device tokens that should return a 410 (so tests
    can assert one bad token doesn't abort the rest).
    """

    def __init__(self, failures: set[str] | None = None):
        self.calls: list[dict] = []
        self.failures = failures or set()

    async def post(self, host: str, device_token: str, headers: dict, json: dict) -> ApnsResult:
        self.calls.append({"host": host, "device_token": device_token, "headers": headers, "json": json})
        if device_token in self.failures:
            return ApnsResult(status_code=410, body="Unregistered")
        return ApnsResult(status_code=200, body="")


def test_apns_token_signer_jwt_header_and_claims(test_ec_key_pem):
    signer = ApnsTokenSigner(private_key=test_ec_key_pem, key_id="T7GUUS93Q3", team_id="TEAMID1234")

    token = signer.sign(now=1_700_000_000.0)

    header = jwt.get_unverified_header(token)
    assert header["kid"] == "T7GUUS93Q3"
    assert header["alg"] == "ES256"

    private_key = serialization.load_pem_private_key(test_ec_key_pem.encode(), password=None)
    public_key = private_key.public_key()
    decoded = jwt.decode(token, key=public_key, algorithms=["ES256"])
    assert decoded["iss"] == "TEAMID1234"
    assert decoded["iat"] == 1_700_000_000


def test_apns_token_signer_caches_token(test_ec_key_pem):
    signer = ApnsTokenSigner(private_key=test_ec_key_pem, key_id="KEYID", team_id="TEAM")

    first = signer.sign(now=1_700_000_000.0)
    second = signer.sign(now=1_700_000_100.0)  # well within TTL

    assert first == second


def test_apns_token_signer_refreshes_after_ttl(test_ec_key_pem):
    signer = ApnsTokenSigner(private_key=test_ec_key_pem, key_id="KEYID", team_id="TEAM")

    first = signer.sign(now=1_700_000_000.0)
    second = signer.sign(now=1_700_000_000.0 + 60 * 60)  # past TTL

    assert first != second


async def test_apns_client_sends_correct_topic_and_host_sandbox(test_ec_key_pem):
    signer = ApnsTokenSigner(private_key=test_ec_key_pem, key_id="KEYID", team_id="TEAM")
    transport = FakeApnsTransport()
    client = ApnsClient(signer, topic="com.spore.app", use_sandbox=True, transport=transport)

    result = await client.send_alert("device-token-1", "Hello", "World")

    assert result.ok
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["host"] == APNS_SANDBOX_HOST
    assert call["device_token"] == "device-token-1"
    assert call["headers"]["apns-topic"] == "com.spore.app"
    assert call["headers"]["apns-push-type"] == "alert"
    assert call["headers"]["authorization"].startswith("bearer ")
    assert call["json"] == {"aps": {"alert": {"title": "Hello", "body": "World"}}}


async def test_apns_client_uses_prod_host_when_not_sandbox(test_ec_key_pem):
    signer = ApnsTokenSigner(private_key=test_ec_key_pem, key_id="KEYID", team_id="TEAM")
    transport = FakeApnsTransport()
    client = ApnsClient(signer, topic="com.spore.app", use_sandbox=False, transport=transport)

    await client.send_alert("device-token-1", "Hello", "World")

    assert transport.calls[0]["host"] == APNS_PROD_HOST


async def test_apns_notifier_sends_to_all_registered_tokens(test_ec_key_pem):
    signer = ApnsTokenSigner(private_key=test_ec_key_pem, key_id="KEYID", team_id="TEAM")
    transport = FakeApnsTransport()
    client = ApnsClient(signer, topic="com.spore.app", use_sandbox=True, transport=transport)

    async def token_provider() -> list[str]:
        return ["device-1", "device-2"]

    notifier = ApnsNotifier(client, token_provider)

    await notifier.send(channel="apns", title="Spore reminder", body="hello", meta={"reminder_id": "abc"})

    assert len(transport.calls) == 2
    sent_tokens = {call["device_token"] for call in transport.calls}
    assert sent_tokens == {"device-1", "device-2"}
    for call in transport.calls:
        assert call["headers"]["apns-topic"] == "com.spore.app"
        assert call["json"]["aps"]["alert"]["title"] == "Spore reminder"
        assert call["json"]["aps"]["alert"]["body"] == "hello"


async def test_apns_notifier_continues_after_failed_token(test_ec_key_pem):
    signer = ApnsTokenSigner(private_key=test_ec_key_pem, key_id="KEYID", team_id="TEAM")
    transport = FakeApnsTransport(failures={"bad-device"})
    client = ApnsClient(signer, topic="com.spore.app", use_sandbox=True, transport=transport)

    async def token_provider() -> list[str]:
        return ["bad-device", "good-device"]

    notifier = ApnsNotifier(client, token_provider)

    await notifier.send(channel="apns", title="t", body="b")

    assert len(transport.calls) == 2
    sent_tokens = {call["device_token"] for call in transport.calls}
    assert sent_tokens == {"bad-device", "good-device"}


async def test_apns_notifier_no_devices_does_not_error():
    class _NoTransport:
        async def post(self, *args, **kwargs):
            raise AssertionError("should not be called when no tokens")

    signer = ApnsTokenSigner(private_key="unused", key_id="K", team_id="T")
    client = ApnsClient.__new__(ApnsClient)  # bypass __init__ to avoid building HttpxApnsTransport
    client.signer = signer
    client.topic = "com.spore.app"
    client.host = APNS_SANDBOX_HOST
    client.transport = _NoTransport()

    async def token_provider() -> list[str]:
        return []

    notifier = ApnsNotifier(client, token_provider)
    await notifier.send(channel="apns", title="t", body="b")  # should not raise


def test_get_notifier_defaults_to_noop_when_apns_disabled():
    notifier = get_notifier()
    assert isinstance(notifier, NoOpNotifier)


def test_get_notifier_returns_noop_without_token_provider(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "apns_enabled", True)
    monkeypatch.setattr(settings, "apns_team_id", "TEAMID")
    monkeypatch.setattr(settings, "apns_key_path", "/nonexistent/AuthKey.p8")

    # No key file present -> falls back to NoOp even with apns_enabled=True
    notifier = get_notifier(token_provider=lambda: [])
    assert isinstance(notifier, NoOpNotifier)


def test_get_notifier_returns_apns_when_configured(tmp_path, monkeypatch, test_ec_key_pem):
    from app.config import settings

    key_path = tmp_path / "AuthKey_TEST.p8"
    key_path.write_text(test_ec_key_pem)

    monkeypatch.setattr(settings, "apns_enabled", True)
    monkeypatch.setattr(settings, "apns_team_id", "TEAMID")
    monkeypatch.setattr(settings, "apns_key_path", str(key_path))

    async def token_provider() -> list[str]:
        return []

    notifier = get_notifier(token_provider=token_provider)
    assert isinstance(notifier, ApnsNotifier)
