from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_ID: int
    ADMIN_IDS: list[int] = [1722837182]
    ADMIN_USERNAME: str = "@yuriiyurii27"
    CHANNEL_ID: str
    DATABASE_URL: str = "sqlite+aiosqlite:///./bot.db"
    REDIS_URL: str = "redis://redis:6379/0"
    WEBHOOK_URL: str | None = None
    WEBHOOK_PORT: int = 8080
    WEBHOOK_SECRET: str = "supersecret"

    @property
    def all_admin_ids(self) -> set[int]:
        """Повертає всіх адмінів — основний + додаткові."""
        return {self.ADMIN_ID} | set(self.ADMIN_IDS)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
