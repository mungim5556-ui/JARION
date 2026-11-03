"""Guacamole encrypted JSON 인증(guacamole-auth-json) 토큰 생성.

포털이 세션마다 1회용 연결 정보를 만들어 암호화해 넘기면, Guacamole 은 이를 해석해
해당 PC 하나에만 접속할 수 있는 임시 사용자를 만든다. Guacamole DB 에 학생 계정이나
연결을 따로 등록할 필요가 없고, 학생은 PC 주소를 알 수 없다.

형식: base64( AES-128-CBC(key, iv=0, PKCS7( HMAC-SHA256(key, json) || json )) )
"""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .config import Settings
from .models import RemoteSession

RECORDING_PATH = "/var/lib/guacamole/recordings"


def encrypt_auth_payload(secret_key_hex: str, payload: dict) -> str:
    key = bytes.fromhex(secret_key_hex)
    if len(key) != 16:
        raise ValueError("Guacamole JSON secret key 는 128bit 여야 합니다")
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    signature = hmac.new(key, body, hashlib.sha256).digest()

    padder = padding.PKCS7(128).padder()
    plain = padder.update(signature + body) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(b"\x00" * 16)).encryptor()
    return base64.b64encode(encryptor.update(plain) + encryptor.finalize()).decode()


def decrypt_auth_payload(secret_key_hex: str, data: str) -> dict:
    """테스트/디버깅용 역변환 (서명 검증 포함)."""
    key = bytes.fromhex(secret_key_hex)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(b"\x00" * 16)).decryptor()
    padded = decryptor.update(base64.b64decode(data)) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    signature, body = plain[:32], plain[32:]
    if not hmac.compare_digest(signature, hmac.new(key, body, hashlib.sha256).digest()):
        raise ValueError("서명 불일치")
    return json.loads(body)


def rdp_parameters(settings: Settings, session: RemoteSession) -> dict[str, str]:
    m = session.machine
    params = {
        "hostname": m.hostname,
        "port": str(m.rdp_port),
        "security": "nla",
        "ignore-cert": "true",
        "resize-method": "display-update",
        "color-depth": "24",
        "enable-font-smoothing": "true",
        "client-name": "JARION",
        "disable-copy": "false" if settings.allow_clipboard_copy else "true",
        "disable-paste": "false" if settings.allow_clipboard_paste else "true",
    }
    if settings.rdp_domain:
        params["domain"] = settings.rdp_domain
    if settings.rdp_prefill_username:
        params["username"] = session.user.username
    if settings.recording_enabled:
        params.update(
            {
                "recording-path": RECORDING_PATH,
                "create-recording-path": "true",
                "recording-name": f"session-{session.id}-{session.user.username}",
            }
        )
    return params


def build_connect_data(settings: Settings, session: RemoteSession, now: datetime) -> tuple[str, datetime]:
    if not settings.guac_json_secret_key:
        raise RuntimeError("JARION_GUAC_JSON_SECRET_KEY 가 설정되지 않았습니다")
    expires = now + timedelta(seconds=settings.guac_token_ttl_seconds)
    payload = {
        "username": f"jarion:{session.user.username}",
        "expires": int(expires.timestamp() * 1000),
        "connections": {
            session.machine.name: {
                "protocol": "rdp",
                "parameters": rdp_parameters(settings, session),
            }
        },
    }
    return encrypt_auth_payload(settings.guac_json_secret_key, payload), expires
