import os
import json
from pydantic import BaseSettings, Field

class Settings(BaseSettings):
    MONGO_URI: str = Field(..., env="MONGO_URI")
    BOT_TOKEN: str = Field(..., env="BOT_TOKEN")
    BOT_SECRET: str = Field(..., env="BOT_SECRET")
    OPENAI_KEY: str = Field(..., env="OPENAI_KEY")
    SERVER_ID: str = Field(..., env="SERVER_ID")
    TWITTER_BEARER_TOKEN: str = Field("", env="TWITTER_BEARER_TOKEN")
    RSS_SOURCES: list = Field(default_factory=list, env="RSS_SOURCES")
    TWITTER_USERS: list = Field(default_factory=list, env="TWITTER_USERS")
    TAG_CHANNEL_MAP: dict = Field(default_factory=dict, env="TAG_CHANNEL_MAP")
    MODMAIL_CHANNEL_ID: int = Field(None, env="MODMAIL_CHANNEL_ID")
    TOX_THRESHOLD: float = Field(0.5, env="TOX_THRESHOLD")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

def _load_json_env(var_name, default):
    val = os.getenv(var_name, "")
    if not val:
        return default
    try:
        return json.loads(val)
    except json.JSONDecodeError:
        return default

settings = Settings()
# parse JSON fields
settings.RSS_SOURCES = _load_json_env("RSS_SOURCES", [])
settings.TWITTER_USERS = _load_json_env("TWITTER_USERS", [])
settings.TAG_CHANNEL_MAP = _load_json_env("TAG_CHANNEL_MAP", {})