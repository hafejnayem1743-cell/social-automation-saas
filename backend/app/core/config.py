import os

class Settings:
    APP_NAME = os.getenv("APP_NAME", "NAYEM BOSS SOCIAL AUTOMATION")
    VERSION = os.getenv("APP_VERSION", "0.1.0")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./social_automation.db")
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-in-production")

settings = Settings()
