import os
import urllib.error
import urllib.request


TARGET_URL = os.environ.get("UNICAMPLINK_URL", "").rstrip("/")
CRON_SECRET = os.environ.get("FRIEND_SUGGESTION_CRON_SECRET", "")

if not TARGET_URL:
    raise RuntimeError("UNICAMPLINK_URL is not set.")

if not CRON_SECRET:
    raise RuntimeError("FRIEND_SUGGESTION_CRON_SECRET is not set.")


url = f"{TARGET_URL}/api/internal/friend-suggestions/run"

request = urllib.request.Request(
    url,
    method="POST",
    headers={
        "X-UniCamplink-Cron-Secret": CRON_SECRET,
        "Accept": "application/json",
    },
)

try:
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read().decode("utf-8")
        print(f"HTTP {response.status}")
        print(body)

except urllib.error.HTTPError as error:
    body = error.read().decode("utf-8", errors="replace")
    print(f"HTTP {error.code}")
    print(body)
    raise SystemExit(1)

except urllib.error.URLError as error:
    print(f"Request failed: {error}")
    raise SystemExit(1)
