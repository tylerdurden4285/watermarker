import json
import logging
import os
import subprocess
import urllib.request

logger = logging.getLogger(__name__)


def trigger_hook(event: str, data: dict) -> None:
    """Trigger a webhook URL or run a command with JSON payload."""
    env_key = f"{event.upper()}_HOOK"
    hook = os.getenv(env_key)
    if not hook:
        return

    try:
        payload = json.dumps(data).encode("utf-8")
        if hook.startswith("http://") or hook.startswith("https://"):
            req = urllib.request.Request(hook, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).close()
        else:
            subprocess.Popen([hook, payload.decode()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        logger.error("Failed to execute %s hook: %s", event, exc)

