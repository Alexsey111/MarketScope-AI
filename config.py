# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# Bot
BOT_TOKEN = os.getenv("BOT_TOKEN")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://user:pass@localhost:5432/marketscope"
)

# JWT Auth
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_ME_IN_PRODUCTION_" + os.urandom(24).hex())
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Security
MAX_BODY_SIZE = 100 * 1024  # 100KB
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

# Subscription limits
FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "5"))
PRO_DAILY_LIMIT = int(os.getenv("PRO_DAILY_LIMIT", "100"))
