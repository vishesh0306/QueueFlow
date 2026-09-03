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
    # Free-tier deploy compromise: platforms like Render don't offer a free Background
    # Worker service type at all, only Web Services -- when this is set, main.py starts
    # worker.py's and telegram_bot.py's loops as daemon threads inside the API process
    # instead of expecting them as separate processes. Off by default: local dev and any
    # real deployment (docker-compose.prod.yml) keep the LLD's actual design, where a
    # slow Telegram/SMTP call can never block an API request thread.
    run_background_workers_in_process: bool = os.environ.get(
        "RUN_BACKGROUND_WORKERS_IN_PROCESS", "false"
    ).lower() == "true"
    jwt_secret: str = os.environ.get("JWT_SECRET", "")
    smtp_host: str = os.environ.get("SMTP_HOST", "localhost")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "25"))
    smtp_username: str = os.environ.get("SMTP_USERNAME", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    smtp_from_address: str = os.environ.get("SMTP_FROM_ADDRESS", "noreply@queueflow.local")


settings = Settings()
