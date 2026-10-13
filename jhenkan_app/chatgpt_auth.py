"""Official Sign in with ChatGPT public-client flow; credentials stay in DPAPI storage."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import msvcrt
import secrets
import threading
import time
import uuid
import webbrowser
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt

from .config import data_dir

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
AUTHORIZE_URL = ISSUER + "/api/accounts/authorize"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
JWKS_URL = ISSUER + "/.well-known/jwks.json"
USAGE_URL = "https://chatgpt.com/#settings/Usage"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
_lock = threading.RLock()


class AuthError(RuntimeError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes, decrypt: bool = False) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    function = (ctypes.windll.crypt32.CryptUnprotectData if decrypt
                else ctypes.windll.crypt32.CryptProtectData)
    # CRYPTPROTECT_UI_FORBIDDEN; the Windows user account protects this blob.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise AuthError("ChatGPTの認証情報をWindowsで保護・読み取りできません。")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(target.data)


@contextmanager
def _storage_lock():
    """Serialize credential rotation across both threads and processes."""
    with _lock:
        directory = data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "chatgpt.lock").open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            deadline = time.monotonic() + 30
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise AuthError("ChatGPTの認証情報が使用中です。少し待ってください。")
                    time.sleep(0.1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _load() -> dict:
    path = data_dir() / "chatgpt-auth.bin"
    if not path.exists():
        return {"host_id": "urn:uuid:" + str(uuid.uuid4()), "accounts": {}}
    try:
        return json.loads(_protect(path.read_bytes(), decrypt=True))
    except (ValueError, OSError) as exc:
        raise AuthError("ChatGPTの認証情報を読み取れません。") from exc


def _save(data: dict) -> None:
    directory = data_dir()
    temporary = directory / "chatgpt-auth.tmp"
    temporary.write_bytes(_protect(json.dumps(data).encode("utf-8")))
    temporary.replace(directory / "chatgpt-auth.bin")


def accounts() -> list[dict]:
    with _storage_lock():
        return [{"client_id": cid, "email": item.get("email", "登録途中"),
                 "connected": bool(item.get("access_token"))}
                for cid, item in _load()["accounts"].items()]


def connected(client_id: str) -> bool:
    return any(item["client_id"] == client_id and item["connected"] for item in accounts())


def _token_request(payload: dict) -> dict:
    try:
        response = httpx.post(TOKEN_URL, data=payload, timeout=20)
        if response.status_code >= 400:
            # Never include the response, code or token in exceptions/logs.
            raise AuthError("ChatGPT認証に失敗しました。もう一度ログインしてください。")
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AuthError("ChatGPT認証サーバーに接続できません。") from exc


class _JWKSClient(jwt.PyJWKClient):
    """Use the app's HTTP transport for public keys as well as token exchange."""
    def fetch_data(self):
        for attempt in range(3):
            try:
                response = httpx.get(self.uri, timeout=self.timeout,
                                     headers={"User-Agent": "JHenkan/1.0"})
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
                    raise jwt.PyJWKClientError("Invalid public key response")
                if self.jwk_set_cache is not None:
                    self.jwk_set_cache.put(data)
                self._last_successful_fetch = time.monotonic()
                return data
            except (httpx.HTTPError, ValueError):
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        raise jwt.PyJWKClientConnectionError("Could not retrieve OpenAI public keys")


def _validate_identity(token: str, client_id: str, nonce: str) -> dict:
    try:
        key = _JWKSClient(JWKS_URL, timeout=10).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id,
                            issuer=ISSUER, options={"require": ["sub", "exp", "iat", "nonce"]})
        if not secrets.compare_digest(str(claims["nonce"]), nonce):
            raise AuthError("ChatGPT認証の確認値が一致しません。")
        return claims
    except jwt.PyJWKClientConnectionError as exc:
        raise AuthError("OpenAIの本人確認用公開鍵を取得できません。通信を確認して再ログインしてください。") from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthError("ChatGPT認証の登録先IDが一致しません。再ログインしてください。") from exc
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("ChatGPTの本人確認が期限切れです。再ログインしてください。") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("ChatGPTの本人確認に失敗しました。") from exc


def _credentials(tokens: dict, previous: dict) -> dict:
    scopes = set(tokens.get("scope", " ".join(previous.get("scopes", []))).split())
    if "chatgpt.tokens.use.direct" not in scopes or "resource.invoke" not in scopes:
        raise AuthError("ChatGPTプランの利用が許可されていません。ログインして利用を許可してください。")
    if not tokens.get("access_token") or tokens.get("token_type", "").lower() != "bearer":
        raise AuthError("ChatGPTの認証情報が不完全です。")
    return {**previous, **{name: tokens[name] for name in
            ("access_token", "refresh_token", "id_token") if name in tokens},
            "scopes": sorted(scopes),
            "expires_at": time.time() + float(tokens.get("expires_in", 3600))}


def sign_in(client_id: str = "", cancel: threading.Event | None = None) -> str:
    cancel = cancel or threading.Event()
    with _storage_lock():
        data = _load()
        _save(data)  # Persist the host ID before opening the browser.
        previous = data["accounts"].get(client_id, {})
        if client_id and client_id not in data["accounts"]:
            raise AuthError("選択されたChatGPTアカウントが見つかりません。")
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    callback = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # The callback URL contains credentials.

        def do_GET(self):
            parsed = urlsplit(self.path)
            values = parse_qs(parsed.query)
            valid = (parsed.path == "/auth/callback" and
                     len(values.get("state", [])) == 1 and
                     secrets.compare_digest(values["state"][0], state))
            if valid:
                callback.update({k: v[0] for k, v in values.items() if len(v) == 1})
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(("認証を受け付けました。JHenkanに戻ってください。" if valid
                              else "無効な認証リクエストです。").encode("utf-8"))

    class CallbackServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(2)
            return connection, address

    with CallbackServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 0.25
        redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
        parameters = {"client_id": client_id or "dynamic_agent_client",
                      "ext_agent_host_id": data["host_id"], "response_type": "code",
                      "redirect_uri": redirect, "scope": SCOPES, "resource": RESOURCE,
                      "state": state, "nonce": nonce, "code_challenge_method": "S256",
                      "code_challenge": base64.urlsafe_b64encode(
                          hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
        if not client_id:
            parameters["agent_name_hint"] = "JHenkan"
        elif previous.get("id_token"):
            parameters["id_token_hint"] = previous["id_token"]
        if previous.get("email"):
            parameters["login_hint"] = previous["email"]
        if not webbrowser.open(AUTHORIZE_URL + "?" + urlencode(parameters)):
            raise AuthError("ログイン用のブラウザーを開けませんでした。")
        deadline = time.monotonic() + 300
        while not callback:
            if cancel.is_set() or time.monotonic() >= deadline:
                raise AuthError("ChatGPTログインを中断しました。もう一度ログインできます。")
            server.handle_request()
    if callback.get("error") or not callback.get("code"):
        raise AuthError("ChatGPTログインが許可されませんでした。")
    issued_id = callback.get("client_id", client_id)
    if not issued_id or issued_id == "dynamic_agent_client" or (client_id and issued_id != client_id):
        raise AuthError("ChatGPTの登録IDを確認できませんでした。")
    with _storage_lock():
        data = _load()
        data["accounts"].setdefault(issued_id, {})  # Retain registration even if exchange fails.
        _save(data)
    tokens = _token_request({"grant_type": "authorization_code", "client_id": issued_id,
                             "code": callback["code"], "code_verifier": verifier,
                             "redirect_uri": redirect, "resource": RESOURCE})
    claims = _validate_identity(tokens.get("id_token", ""), issued_id, nonce)
    if previous.get("subject") and previous["subject"] != claims["sub"]:
        raise AuthError("ログインしたChatGPTアカウントが選択したアカウントと異なります。")
    profile = _credentials(tokens, {"subject": claims["sub"], "email": claims.get("email", ""),
                                    "client_id": issued_id})
    if cancel.is_set():
        raise AuthError("ChatGPTログインを中断しました。")
    with _storage_lock():
        data = _load()
        existing = data["accounts"].get(issued_id, {})
        if existing.get("subject") and existing["subject"] != claims["sub"]:
            raise AuthError("登録済みのChatGPTアカウントと一致しません。")
        data["accounts"][issued_id] = profile
        _save(data)
    return issued_id


def access_token(client_id: str) -> str:
    with _storage_lock():
        data = _load()
        profile = data["accounts"].get(client_id, {})
        if not profile.get("access_token"):
            raise AuthError("設定画面でChatGPTにログインしてください。")
        if profile.get("expires_at", 0) <= time.time() + 60:
            if not profile.get("refresh_token"):
                raise AuthError("ChatGPTにもう一度ログインしてください。")
            tokens = _token_request({"grant_type": "refresh_token", "client_id": client_id,
                                     "refresh_token": profile["refresh_token"], "resource": RESOURCE})
            profile = _credentials(tokens, profile)
            data["accounts"][client_id] = profile
            _save(data)
        return profile["access_token"]


def list_models(client_id: str) -> list[dict]:
    try:
        response = httpx.get(RESOURCE + "/models", headers={
            "Authorization": "Bearer " + access_token(client_id)}, timeout=20)
        response.raise_for_status()
        return [{"slug": model["slug"], "display_name": model.get("display_name", model["slug"])}
                for model in response.json()["models"] if model.get("visibility") == "list"]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise AuthError("ChatGPTのモデル一覧を取得できません。接続を確認して再読み込みしてください。") from exc


def sign_out(client_id: str) -> bool:
    """Return whether remote revocation was confirmed; always clear local tokens."""
    with _storage_lock():
        data = _load()
        profile = data["accounts"].get(client_id, {})
        confirmed = not profile.get("refresh_token")
        if not confirmed:
            try:
                discovery = httpx.get(ISSUER + "/.well-known/openid-configuration", timeout=15)
                discovery.raise_for_status()
                endpoint = discovery.json()["revocation_endpoint"]
                if urlsplit(endpoint).scheme != "https" or urlsplit(endpoint).netloc != "auth.openai.com":
                    raise AuthError("認証サーバーの情報を確認できません。")
                for delay in (0, 0.5, 1):
                    time.sleep(delay)
                    try:
                        response = httpx.post(endpoint, data={"token": profile["refresh_token"],
                            "token_type_hint": "refresh_token", "client_id": client_id}, timeout=15)
                    except httpx.HTTPError:
                        continue
                    if response.status_code == 200:
                        confirmed = True
                        break
                    if response.status_code < 500:
                        break
            except (httpx.HTTPError, ValueError, KeyError, AuthError):
                pass
        for name in ("access_token", "refresh_token", "id_token", "expires_at", "scopes"):
            profile.pop(name, None)
        if client_id in data["accounts"]:
            _save(data)
        return confirmed
