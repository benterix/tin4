from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://tin4:changeme@postgres:5432/tin4"
    redis_url: str = "redis://redis:6379/0"
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672/"
    redpanda_brokers: str = "redpanda:9092"

    jwt_secret: str = "supersecretkey_change_in_production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    domain: str = "localhost"
    tcp_server_port: int = 9000

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
