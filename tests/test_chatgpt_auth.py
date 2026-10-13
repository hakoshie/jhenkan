import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from jhenkan_app import chatgpt_auth as auth


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "data_dir", lambda: tmp_path)
    return tmp_path


def profile(**extra):
    return {"subject": "user", "email": "user@example.com", "client_id": "oaiapp_test",
            "access_token": "access-secret", "refresh_token": "refresh-secret",
            "id_token": "id-secret", "scopes": ["chatgpt.tokens.use.direct", "resource.invoke"],
            "expires_at": time.time() + 3600, **extra}


def seed(value):
    with auth._storage_lock():
        data = auth._load()
        data["accounts"]["oaiapp_test"] = value
        auth._save(data)
        return data["host_id"]


def test_credentials_are_encrypted_and_host_survives_reload(storage):
    host = seed(profile())
    encrypted = (storage / "chatgpt-auth.bin").read_bytes()
    assert b"access-secret" not in encrypted
    assert b"refresh-secret" not in encrypted
    assert auth._load()["host_id"] == host
    assert auth.access_token("oaiapp_test") == "access-secret"
    assert "access_token" not in auth.accounts()[0]


def test_concurrent_refresh_rotates_once_and_keeps_other_accounts(storage):
    seed(profile(expires_at=0))
    with auth._storage_lock():
        data = auth._load()
        data["accounts"]["oaiapp_other"] = profile(access_token="other-secret")
        auth._save(data)
    tokens = {"access_token": "new-access", "refresh_token": "new-refresh",
              "token_type": "Bearer", "expires_in": 3600}
    with patch.object(auth, "_token_request", return_value=tokens) as request:
        with ThreadPoolExecutor(max_workers=3) as pool:
            assert list(pool.map(auth.access_token, ["oaiapp_test"] * 3)) == ["new-access"] * 3
        request.assert_called_once()
        assert request.call_args.args[0]["client_id"] == "oaiapp_test"
    assert auth._load()["accounts"]["oaiapp_test"]["refresh_token"] == "new-refresh"
    assert auth.access_token("oaiapp_other") == "other-secret"


@pytest.mark.parametrize("scope", ["openid email", "chatgpt.tokens.use.direct"])
def test_missing_plan_permission_is_rejected(scope):
    with pytest.raises(auth.AuthError, match="利用が許可"):
        auth._credentials({"access_token": "secret", "token_type": "Bearer", "scope": scope}, {})


@pytest.mark.parametrize("change", [{"nonce": "wrong"}, {"aud": "other"},
                                   {"iss": "https://other.example"}, {"exp": 1}])
def test_id_token_verifies_signature_audience_issuer_expiry_and_nonce(change):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = {"sub": "user", "iss": auth.ISSUER, "aud": "oaiapp_test",
              "iat": int(time.time()), "exp": int(time.time()) + 3600, "nonce": "nonce"}
    token = jwt.encode(claims, key, algorithm="RS256")
    bad = jwt.encode({**claims, **change}, key, algorithm="RS256")
    with patch.object(auth, "_JWKSClient") as jwks:
        jwks.return_value.get_signing_key_from_jwt.return_value = SimpleNamespace(key=key.public_key())
        assert auth._validate_identity(token, "oaiapp_test", "nonce")["sub"] == "user"
        with pytest.raises(auth.AuthError):
            auth._validate_identity(bad, "oaiapp_test", "nonce")
        forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(claims, forged_key, algorithm="RS256")
        with pytest.raises(auth.AuthError):
            auth._validate_identity(forged, "oaiapp_test", "nonce")


def test_signin_ignores_wrong_state_and_exchanges_with_issued_client(storage):
    requests = []
    callback_thread = None
    def browser(url):
        nonlocal callback_thread
        params = parse_qs(urlsplit(url).query)
        requests.append(params)
        def callbacks():
            first = httpx.get(params["redirect_uri"][0], params={"state": "wrong", "code": "bad"})
            assert first.status_code == 400
            httpx.get(params["redirect_uri"][0], params={"state": params["state"][0],
                       "code": "good", "client_id": "oaiapp_new"})
        callback_thread = threading.Thread(target=callbacks)
        callback_thread.start()
        return True
    tokens = {"access_token": "secret", "refresh_token": "refresh", "id_token": "id",
              "token_type": "Bearer", "scope": auth.SCOPES, "expires_in": 3600}
    with patch.object(auth.webbrowser, "open", side_effect=browser), \
            patch.object(auth, "_token_request", return_value=tokens) as exchange, \
            patch.object(auth, "_validate_identity", return_value={"sub": "user", "email": "user@example.com"}):
        assert auth.sign_in() == "oaiapp_new"
        callback_thread.join(timeout=3)
        payload = exchange.call_args.args[0]
        assert payload["client_id"] == "oaiapp_new"
        assert payload["code"] == "good"
        assert payload["redirect_uri"] == requests[0]["redirect_uri"][0]
        assert requests[0]["client_id"] == ["dynamic_agent_client"]
        assert requests[0]["agent_name_hint"] == ["JHenkan"]
        assert requests[0]["ext_agent_host_id"] == [auth._load()["host_id"]]
    assert auth.connected("oaiapp_new")


def test_logout_clears_tokens_but_preserves_registration(storage):
    host = seed(profile())
    with patch.object(auth.httpx, "get", return_value=httpx.Response(200,
            json={"revocation_endpoint": auth.ISSUER + "/api/accounts/oauth/revoke"},
            request=httpx.Request("GET", auth.ISSUER))), \
            patch.object(auth.httpx, "post", return_value=httpx.Response(200)):
        assert auth.sign_out("oaiapp_test") is True
    saved = auth._load()
    assert saved["host_id"] == host
    assert saved["accounts"]["oaiapp_test"]["subject"] == "user"
    assert not auth.connected("oaiapp_test")
    assert "refresh_token" not in saved["accounts"]["oaiapp_test"]


def test_models_use_account_token_and_visibility(storage):
    seed(profile())
    response = httpx.Response(200, json={"models": [
        {"slug": "gpt-6-luna", "display_name": "Luna", "visibility": "list"},
        {"slug": "hidden", "visibility": "hide"}]},
        request=httpx.Request("GET", auth.RESOURCE + "/models"))
    with patch.object(auth.httpx, "get", return_value=response) as request:
        assert auth.list_models("oaiapp_test") == [{"slug": "gpt-6-luna", "display_name": "Luna"}]
        assert request.call_args.kwargs["headers"] == {"Authorization": "Bearer access-secret"}


def test_logout_network_failure_retries_and_reports_unconfirmed(storage):
    seed(profile())
    discovery = httpx.Response(200, json={"revocation_endpoint": auth.ISSUER + "/api/accounts/oauth/revoke"},
                               request=httpx.Request("GET", auth.ISSUER))
    with patch.object(auth.httpx, "get", return_value=discovery), \
            patch.object(auth.httpx, "post", side_effect=httpx.ConnectError("offline")) as revoke, \
            patch.object(auth.time, "sleep"):
        assert auth.sign_out("oaiapp_test") is False
        assert revoke.call_count == 3
    assert not auth.connected("oaiapp_test")


def test_public_keys_retry_transient_failure_without_skipping_validation():
    unavailable = httpx.Response(503, request=httpx.Request("GET", auth.JWKS_URL))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="test", use="sig", alg="RS256")
    success = httpx.Response(200, json={"keys": [public]},
                            request=httpx.Request("GET", auth.JWKS_URL))
    claims = {"sub": "user", "iss": auth.ISSUER, "aud": "oaiapp_test",
              "iat": int(time.time()), "exp": int(time.time()) + 3600, "nonce": "nonce"}
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
    with patch.object(auth.httpx, "get", side_effect=[unavailable, success]) as request, \
            patch.object(auth.time, "sleep"):
        assert auth._validate_identity(token, "oaiapp_test", "nonce")["sub"] == "user"
        assert request.call_count == 2


def test_public_key_network_failure_has_specific_message():
    with patch.object(auth.httpx, "get", side_effect=httpx.ConnectError("offline")), \
            patch.object(auth.time, "sleep"):
        with pytest.raises(auth.AuthError, match="公開鍵を取得できません"):
            auth._validate_identity("eyJhbGciOiJSUzI1NiIsImtpZCI6InRlc3QifQ.eyJzdWIiOiJ1c2VyIn0.eA",
                                    "oaiapp_test", "nonce")
