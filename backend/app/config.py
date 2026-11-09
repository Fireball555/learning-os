import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


class Settings:
    admin_dsn = os.environ.get("ADMIN_DATABASE_URL", "")      # owner role: app schema read/write
    learner_dsn = os.environ.get("LEARNER_DATABASE_URL", "")  # learner_ro: shop schema read-only
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    # Fallback chain, tried in order when a model is rate-limited or unavailable.
    # Same chain for both arms; every hint row records which model wrote it.
    groq_models = [m.strip() for m in os.environ.get(
        "GROQ_MODELS",
        f"{os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')},openai/gpt-oss-120b,openai/gpt-oss-20b,llama-3.1-8b-instant",
    ).split(",") if m.strip()]
    allow_origins = [o for o in os.environ.get("ALLOW_ORIGINS", "").split(",") if o]
    frontend_dist = ROOT / "frontend" / "dist"
    questions_json = Path(__file__).with_name("questions.json")


settings = Settings()
