"""Entry point: runs uvicorn on a background thread and opens a pywebview window.

Usage:
  python backend/main.py             # production, serves frontend/dist
  python backend/main.py --dev       # window points at the Vite dev server (5173)
  python backend/main.py --headless  # API only, no window
"""
import socket
import sys
import threading
import time

import uvicorn
import webview

from app import app

PORT = 8756
DEV_URL = "http://localhost:5173"


class JsApi:
    """Native bridge the frontend reaches through window.pywebview.api."""

    def __init__(self):
        self.window = None

    def pick_folder(self):
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            return result[0] if isinstance(result, (list, tuple)) else result
        return None


def _run_server():
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def _wait_for_server(timeout: float = 15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("API sunucusu başlatılamadı")


if __name__ == "__main__":
    headless = "--headless" in sys.argv
    dev = "--dev" in sys.argv

    if headless:
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
        sys.exit(0)

    threading.Thread(target=_run_server, daemon=True).start()
    _wait_for_server()

    api = JsApi()
    url = DEV_URL if dev else f"http://127.0.0.1:{PORT}"
    window = webview.create_window(
        "Facey", url, js_api=api, width=1240, height=840, min_size=(960, 640))
    api.window = window
    webview.start()
