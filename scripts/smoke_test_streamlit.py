"""Smoke test for the Streamlit web UI.

Starts the server on port 8765, hits the health endpoint, then exits.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "orchestrator" / "web.py"

PORT = 8767
env = {**os.environ, "JOYCAD_LLM_PROVIDER": "mock"}
proc = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", str(WEB),
     "--server.port", str(PORT),
     "--server.headless", "true",
     "--browser.gatherUsageStats", "false"],
    cwd=str(ROOT), env=env,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE)

print(f"started streamlit pid={proc.pid} on port {PORT}, waiting 25s for boot…")
time.sleep(25)

try:
    r = requests.get(f"http://localhost:{PORT}/_stcore/health", timeout=10)
    print(f"health: {r.status_code} {r.text[:80]!r}")
    if r.status_code == 200 and "ok" in r.text.lower():
        print("✓ Streamlit MVP UI is up and healthy")
    else:
        print("✗ Streamlit not healthy")
finally:
    proc.terminate()
    try:
        out, err = proc.communicate(timeout=8)
        print("\n--- stdout tail ---")
        print(out.decode()[-800:])
        print("\n--- stderr tail ---")
        print(err.decode()[-1500:])
    except subprocess.TimeoutExpired:
        proc.kill()
