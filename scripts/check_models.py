"""Check which Groq models in the fallback chain answer right now with your key.
Run before each session:  python scripts/check_models.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import settings  # noqa: E402

from groq import Groq  # noqa: E402

if not settings.groq_api_key:
    sys.exit("GROQ_API_KEY not set in .env")
client = Groq(api_key=settings.groq_api_key, timeout=15.0, max_retries=0)
for m in settings.groq_models:
    t0 = time.perf_counter()
    kw = dict(model=m, messages=[{"role": "user", "content": "Reply with the single word OK."}])
    kw.update(max_completion_tokens=300, reasoning_effort="low") if "gpt-oss" in m else kw.update(max_tokens=5)
    try:
        r = client.chat.completions.create(**kw)
        print(f"OK    {m:40s} {int((time.perf_counter()-t0)*1000)} ms  -> {(r.choices[0].message.content or '').strip()[:20]!r}")
    except Exception as e:
        print(f"FAIL  {m:40s} {type(e).__name__}: {str(e)[:120]}")
