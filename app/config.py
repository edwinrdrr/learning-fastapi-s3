"""App configuration, read from environment variables (12-factor style).

The same Settings work for local MinIO and real AWS S3 — only the values change.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Storage (S3 / MinIO) ---
    # None => boto3 uses the real AWS endpoint. Set to http://minio:9000 locally.
    s3_endpoint_url: str | None = None
    # None => boto3's default credential chain (env, ~/.aws, or an IAM role).
    # Prefer IAM roles in production over static keys.
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "us-east-1"
    s3_bucket: str = "readings"

    # --- API security ---
    # When set, clients must send `X-API-Key: <value>`. Leave unset to disable
    # auth (local/dev). Set it before any non-local deployment.
    api_key: str | None = None
    # Comma-separated allowed CORS origins. "*" allows any (fine for dev).
    cors_origins: str = "*"
    # Global rate limit (slowapi syntax), e.g. "120/minute".
    rate_limit: str = "120/minute"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
