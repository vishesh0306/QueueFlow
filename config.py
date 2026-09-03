import os


class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL", "postgresql://queueflow:queueflow@localhost:5432/queueflow"
    )
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    telegram_bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_bot_username: str = os.environ.get("TELEGRAM_BOT_USERNAME", "")
    # Used to build links that get sent back through Telegram/email -- can't just assume
    # localhost, since the pilot may not run on the same machine a patient's phone reaches.
    public_base_url: str = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
    jwt_secret: str = os.environ.get("JWT_SECRET", "")
    smtp_host: str = os.environ.get("SMTP_HOST", "localhost")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "25"))
    smtp_username: str = os.environ.get("SMTP_USERNAME", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    smtp_from_address: str = os.environ.get("SMTP_FROM_ADDRESS", "noreply@queueflow.local")


settings = Settings()
