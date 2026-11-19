#!/usr/bin/env python3
"""Serve the preview build at http://127.0.0.1:<port>/ until Ctrl+C.

The preview (drafts/_site, written by `python3 build.py --preview`) is laid over the repository:
a request is answered from drafts/_site when that file exists there, otherwise from the
repository, so style.css, images and cv.pdf come from the working copy. It listens on 127.0.0.1
only, so nothing outside this computer can reach it.

Usage: python3 tools/serve.py [port]      (default 8000)
"""
from __future__ import annotations

import http.server
import os
import sys
from functools import partial
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
OVERLAY = ROOT / "drafts" / "_site"
DEFAULT_PORT = 8000


def pick(rel_path: str, overlay: Path, root: Path) -> Path:
    """The file to serve for a site-relative path: the overlay's when it exists, else the repository's.

    `rel_path` is the URL path without its leading slash ("" for /, "commonplace/" for
    /commonplace/). A path ending in "/" means that folder's index.html. Absolute paths and ".."
    raise ValueError, so nothing outside the two folders can be picked.
    """
    pure = PurePosixPath(rel_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe path {rel_path!r}")
    name = rel_path + "index.html" if rel_path in ("", ".") or rel_path.endswith("/") else rel_path
    candidate = overlay / name
    return candidate if candidate.exists() else root / name


class OverlayHandler(http.server.SimpleHTTPRequestHandler):
    """The standard file server, with pick() choosing between the overlay and the repository."""

    def __init__(self, *args, overlay: Path, **kwargs) -> None:
        self.overlay = overlay           # set first: the parent's __init__ handles the request
        super().__init__(*args, **kwargs)

    def translate_path(self, path: str) -> str:
        """Map a request to a file. The parent strips the query and any "..", under the repository."""
        local = super().translate_path(path)
        rel_path = Path(os.path.relpath(local, self.directory)).as_posix()
        rel_path = "" if rel_path == "." else rel_path + ("/" if local.endswith("/") else "")
        return str(pick(rel_path, self.overlay, Path(self.directory)))

    def end_headers(self) -> None:
        """Tell the browser not to cache, so a rebuilt page shows on reload."""
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def parse_port(argv: list[str]) -> int:
    """The port from the command line, or DEFAULT_PORT."""
    if len(argv) > 1 or (argv and not argv[0].isdigit()):
        raise SystemExit("usage: python3 tools/serve.py [port]")
    return int(argv[0]) if argv else DEFAULT_PORT


def main(argv: list[str]) -> int:
    """Serve until Ctrl+C."""
    port = parse_port(argv)
    if not OVERLAY.is_dir():
        print(f"serve.py: {OVERLAY.relative_to(ROOT)} not found; run python3 build.py --preview first",
              file=sys.stderr)
        return 1
    handler = partial(OverlayHandler, directory=str(ROOT), overlay=OVERLAY)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Serving http://127.0.0.1:{port}/ ({OVERLAY.relative_to(ROOT)} over the repository); Ctrl+C to stop")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
