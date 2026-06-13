# Best-effort: flush the Next.js dashboard Data Cache after a prod refresh.
"""
revalidate_website.py — POST to the website's /api/revalidate endpoint to flush the
dashboard cache (tag 'dashboard'), so the site re-fetches fresh data on the next view.

Run this as the LAST step, AFTER `dbt run --target prod` has rebuilt store_pipeline —
not after the source load alone (the dashboard reads the rebuilt store_pipeline.* tables).

Reads from .env:
  REVALIDATE_SECRET  — shared secret (REQUIRED; must match the website's NEXT_REVALIDATE_SECRET)
  WEBSITE_BASE_URL   — e.g. https://<domain> (default: http://localhost:3000)

Best-effort: never raises / never fails the pipeline. Uses stdlib only (no new deps).

  uv run python scripts/revalidate_website.py
"""
import os
import sys
import logging
import urllib.request
import urllib.error
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def revalidate_website() -> bool:
    """Fire the website cache-invalidation webhook. Returns True on HTTP 200."""
    secret = os.environ.get("REVALIDATE_SECRET")
    base = os.environ.get("WEBSITE_BASE_URL", "http://localhost:3000").rstrip("/")

    if not secret:
        log.warning("REVALIDATE_SECRET not set in .env — skipping website cache invalidation.")
        return False

    url = f"{base}/api/revalidate"
    req = urllib.request.Request(
        url,
        data=b"{}",
        method="POST",
        headers={"x-revalidate-secret": secret, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", "replace")[:200]
            log.info("website revalidate OK — HTTP %s %s", resp.status, body)
            return resp.status == 200
    except urllib.error.HTTPError as he:
        # 401 = bad/missing secret; 500 = secret not configured on the website
        log.warning("website revalidate failed — HTTP %s at %s", he.code, url)
    except Exception as ex:
        log.warning("website revalidate unreachable (%s) — %s", url, str(ex)[:90])
    return False


if __name__ == "__main__":
    revalidate_website()
