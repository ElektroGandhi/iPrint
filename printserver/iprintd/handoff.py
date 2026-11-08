"""Hands finished jobs to Home Assistant through the integration's webhook, which can only print."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

from PIL import Image

TIMEOUT = 150  # a held job prints while we wait, and the longest allowed one takes about a minute
# Only the integration answers this. Home Assistant says 200 to a webhook it does not know, and reading that as success
# lost a job while reporting it as printed (measured 07.11.2026).
ACCEPTED = 201


class Offline(Exception):
    pass


class QueueFull(Exception):
    pass


class Handoff:
    def __init__(self, url: str) -> None:
        self.url = url

    def _post(self, body: bytes, content_type: str, label: str = "", queue: str = "print") -> int:
        request = urllib.request.Request(self.url, data=body, method="POST",
                                         headers={"Content-Type": content_type, "X-IPrint-Queue": queue,
                                                  "X-IPrint-Label": label.encode("ascii", "replace").decode()})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
                return answer.status
        except urllib.error.HTTPError as err:
            return err.code
        except OSError as err:
            raise Offline(str(err)) from err

    def send(self, dots: Image.Image, label: str, queue: str = "print") -> None:
        buffer = io.BytesIO()
        dots.save(buffer, "PNG", optimize=True)
        status = self._post(buffer.getvalue(), "image/png", label, queue)
        if status == 507:
            raise QueueFull()
        if status != ACCEPTED:
            raise Offline(f"webhook answered {status}: wrong address, or the print server option is off")

    def ask(self, label: str, url: str) -> None:
        """A job waits for a choice. Home Assistant shows a notification with the link."""
        body = json.dumps({"question": {"label": label, "url": url}}).encode()
        status = self._post(body, "application/json", label)
        if status != ACCEPTED:
            raise Offline(f"webhook answered {status}")

    def report_refusal(self, label: str, reason: str) -> None:
        """Best effort: the client gets the refusal in any case."""
        body = json.dumps({"refused": reason, "label": label}).encode()
        try:
            self._post(body, "application/json", label)
        except Offline:
            pass
