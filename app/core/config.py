from pydantic import BaseModel


class AppSettings(BaseModel):
    name: str = "arch-fastapi"
    env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"
