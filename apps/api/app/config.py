from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경 변수(JARION_ 접두사)로 설정한다."""

    model_config = SettingsConfigDict(env_prefix="JARION_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./jarion.db"

    # 로그인 토큰
    jwt_secret: str = "dev-insecure-change-me"
    jwt_ttl_minutes: int = 480
    cookie_secure: bool = True

    # Guacamole encrypted JSON 인증 (guacamole 컨테이너의 JSON_SECRET_KEY 와 같은 값, 32자리 hex)
    guac_json_secret_key: str = ""
    guac_base_path: str = "/guacamole"
    guac_token_ttl_seconds: int = 300
    allow_clipboard_copy: bool = True   # 원격 PC -> 학생 PC
    allow_clipboard_paste: bool = True  # 학생 PC -> 원격 PC
    recording_enabled: bool = False
    # 학생이 RDP 로그인 창에서 본인 학교(AD) 계정을 입력한다. 포털 아이디 = AD 아이디이면 미리 채워줄 수 있다.
    rdp_domain: str = ""
    rdp_prefill_username: bool = False

    # 세션 정책
    session_max_minutes: int = 240
    no_show_minutes: int = 15
    boot_timeout_seconds: int = 300
    wake_retry_after_seconds: int = 90
    wake_max_attempts: int = 3
    wake_failure_cooldown_minutes: int = 30

    # PC 상태 확인 (게이트웨이에서 각 PC 의 RDP 포트로 TCP 연결 시도)
    scheduler_enabled: bool = True
    probe_interval_seconds: int = 10
    probe_timeout_seconds: float = 1.5
    probe_workers: int = 32

    # WoL 릴레이 인증 토큰 (tools/wol/relay.py 의 RELAY_TOKEN 과 같은 값)
    relay_token: str = ""

    @field_validator("guac_json_secret_key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        if v:
            try:
                key = bytes.fromhex(v)
            except ValueError as e:
                raise ValueError("guac_json_secret_key 는 16진수여야 합니다") from e
            if len(key) != 16:
                raise ValueError("guac_json_secret_key 는 32자리 hex(128bit)여야 합니다")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
