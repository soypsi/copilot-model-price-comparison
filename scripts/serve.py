#!/usr/bin/env python3
"""Serve the site locally and reload connected browsers when files change."""

from __future__ import annotations

import queue
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

HOST: Final = "127.0.0.1"
PORT: Final = 8000
POLL_INTERVAL: Final = 0.5
IGNORED_PARTS: Final = {".git", "__pycache__"}


class ReloadState:
    def __init__(self) -> None:
        self._clients: set[queue.Queue[None]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[None]:
        client: queue.Queue[None] = queue.Queue()
        with self._lock:
            self._clients.add(client)
        return client

    def unsubscribe(self, client: queue.Queue[None]) -> None:
        with self._lock:
            self._clients.discard(client)

    def notify(self) -> None:
        with self._lock:
            clients = tuple(self._clients)
        for client in clients:
            client.put_nowait(None)


reload_state = ReloadState()


def file_snapshot(root: Path) -> dict[Path, int]:
    return {
        path: path.stat().st_mtime_ns
        for path in root.rglob("*")
        if path.is_file() and not IGNORED_PARTS.intersection(path.parts)
    }


def watch_files(root: Path) -> None:
    previous = file_snapshot(root)
    while True:
        time.sleep(POLL_INTERVAL)
        current = file_snapshot(root)
        if current != previous:
            previous = current
            reload_state.notify()


class RequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if urlparse(self.path).path == "/__reload":
            self.send_reload_events()
            return
        super().do_GET()

    def send_reload_events(self) -> None:
        client = reload_state.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                client.get()
                self.wfile.write(b"data: reload\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            reload_state.unsubscribe(client)

    def log_message(self, format: str, *args: object) -> None:
        if urlparse(self.path).path != "/__reload":
            super().log_message(format, *args)


def main() -> None:
    root = Path.cwd()
    watcher = threading.Thread(target=watch_files, args=(root,), daemon=True)
    watcher.start()
    server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    server.daemon_threads = True
    print(f"Serving {root} at http://{HOST}:{PORT} (auto-reload enabled)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
