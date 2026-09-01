import os


class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL", "postgresql://queueflow:queueflow@localhost:5432/queueflow"
    )
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    telegram_bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    jwt_secret: str = os.environ.get("JWT_SECRET", "")


settings = Settings()
