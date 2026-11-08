"""The IPP service. Jobs are checked while the client waits, so a refusal reaches it as the answer to its request."""
from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
import shutil
import threading
import time
import uuid

from . import ipp
from .handoff import Handoff, Offline, QueueFull
from . import editor
from .choice import Choices, Waiting, message_page, page
from .job import finish_label, process, process_label
from .messages import say
from .printer import FORMATS, printer_attributes

_LOGGER = logging.getLogger("iprintd")
MAX_BODY = 64 * 1024 * 1024
MAX_JOBS_KEPT = 50
PENDING, HELD, PROCESSING, CANCELED, ABORTED, COMPLETED = 3, 4, 5, 7, 8, 9


@dataclass
class Job:
    id: int
    name: str
    state: int
    reason: str = "none"
    message: str = ""
    user: str = ""
    queue: str = "print"


class Service:
    """Everything shared between requests. One job goes through OCR at a time: the machine has other work."""

    def __init__(self, handoff: Handoff, address: str, port: int, unique: uuid.UUID, language: str,
                 ask: bool = False) -> None:
        self.handoff = handoff
        # Off by default since 0.2.0b3: a question nobody sees holds the job for ever (08.11.2026). With it on,
        # returns wait for a choice page and photos for the editor page.
        self.ask = ask
        self.uri = f"ipp://{address}:{port}/ipp/print"
        self.uris = {queue: f"ipp://{address}:{port}/ipp/{queue}" for queue in ("print", "label")}
        self.admin = f"http://{address}:{port}/"
        self.unique = unique
        self.language = language
        self.started = time.monotonic()
        self.jobs: dict[int, Job] = {}
        self._next = 1
        self._lock = threading.Lock()
        self._work = threading.Lock()
        self.choices = Choices()

    def new_job(self, name: str, user: str, state: int = PENDING, queue: str = "print") -> Job:
        with self._lock:
            job = Job(self._next, name or "Untitled", state, user=user, queue=queue)
            self._next += 1
            self.jobs[job.id] = job
            while len(self.jobs) > MAX_JOBS_KEPT:
                self.jobs.pop(min(self.jobs))
            return job

    def job_group(self, job: Job) -> bytes:
        return b"".join((
            ipp.attribute(ipp.URI, "job-uri", f"{self.uris[job.queue]}/{job.id}"),
            ipp.attribute(ipp.INTEGER, "job-id", job.id),
            ipp.attribute(ipp.ENUM, "job-state", job.state),
            ipp.attribute(ipp.KEYWORD, "job-state-reasons", job.reason),
            ipp.attribute(ipp.TEXT, "job-state-message", job.message or "ok"),
            ipp.attribute(ipp.NAME, "job-name", job.name),
            ipp.attribute(ipp.NAME, "job-originating-user-name", job.user or "anonymous"),
            ipp.attribute(ipp.URI, "job-printer-uri", self.uris[job.queue]),
            ipp.attribute(ipp.INTEGER, "time-at-creation", max(1, int(time.monotonic() - self.started))),
        ))

    def run(self, job: Job, data: bytes, mime: str) -> tuple[int, str]:
        """Returns the IPP status and message for the request that delivered the document."""
        job.state = PROCESSING
        with self._work:
            try:
                result = (process_label(data, self.language, self.ask) if job.queue == "label"
                          else process(data, mime, self.language, self.ask))
            except Exception:  # noqa: BLE001  OCR broke: say so, and never let a document through unchecked
                _LOGGER.exception("job %s could not be checked", job.id)
                return self._fail(job, ipp.INTERNAL_ERROR, say(self.language, "broken"), "aborted-by-system")
        if result.document is not None:
            return self._hold(job, result)
        if result.picture is not None:
            return self._hold_picture(job, result.picture)
        return self._deliver(job, result)

    def _hold_picture(self, job: Job, picture) -> tuple[int, str]:
        token = self.choices.add(Waiting(job.id, job.name, picture=picture))
        return self._ask(job, token, f"{self.admin}bild/{token}", "wait_edit")

    def _ask(self, job: Job, token: str, url: str, key: str) -> tuple[int, str]:
        job.state, job.reason = HELD, "job-hold-until-specified"
        job.message = say(self.language, key, url=url)
        try:
            self.handoff.ask(job.name, url)
        except Offline as err:
            _LOGGER.error("asking about job %s failed: %s", job.id, err)
            self.choices.take(token)
            return self._fail(job, ipp.TEMPORARY_ERROR, say(self.language, "offline"), "aborted-by-system")
        _LOGGER.info("job %s '%s' waits: %s", job.id, job.name, key)
        return ipp.OK, job.message

    def edit(self, token: str, values: dict) -> tuple[bool, str]:
        """The editor page was sent: print the photo with these settings."""
        waiting = self.choices.get(token)
        if waiting is None or waiting.picture is None:
            _LOGGER.info("photo %s… came in, but nothing waits for it", token[:6])
            return False, say(self.language, "gone")
        dots = editor.apply(waiting.picture, editor.Settings.parse(values))
        if editor.too_long(dots):
            return False, say(self.language, "edit_long")   # keep it waiting: crop and send again
        self.choices.take(token)
        job = self.jobs.get(waiting.job_id) or Job(waiting.job_id, waiting.label, HELD)
        job.state = PROCESSING
        from .job import Result
        status, message = self._deliver(job, Result(dots=dots))
        return status == ipp.OK, message or say(self.language, "printed")

    def _hold(self, job: Job, result) -> tuple[int, str]:
        """Two ways in one document: the job waits, Home Assistant shows the link to the choice page."""
        token = self.choices.add(Waiting(job.id, job.name, document=result.document))
        return self._ask(job, token, f"{self.admin}wahl/{token}", "wait_choice")

    def decide(self, token: str, way: str, captions: bool) -> tuple[bool, str]:
        """The choice page was sent. Returns success and the text to show."""
        waiting = self.choices.take(token)
        if waiting is None or waiting.document is None or way not in ("shop", "label"):
            _LOGGER.info("choice %s… came in, but nothing waits for it", token[:6])
            return False, say(self.language, "gone")
        _LOGGER.info("job %s '%s' chosen: %s, identifier %s", waiting.job_id, waiting.label, way, captions)
        job = self.jobs.get(waiting.job_id) or Job(waiting.job_id, waiting.label, HELD, queue="label")
        job.state = PROCESSING
        with self._work:
            result = finish_label(waiting.document, way, captions, self.language)
        status, message = self._deliver(job, result)
        return status == ipp.OK, message or say(self.language, "printed")

    def _deliver(self, job: Job, result) -> tuple[int, str]:
        if result.dots is None:
            _LOGGER.info("job %s '%s' refused: %s", job.id, job.name, result.refused)
            self.handoff.report_refusal(job.name, result.refused)
            status = ipp.DOCUMENT_FORMAT_ERROR if result.broken else ipp.DOCUMENT_UNPRINTABLE
            return self._fail(job, status, result.refused, "document-unprintable-error")
        try:
            slips = result.slips or [result.dots]
            for number, slip in enumerate(slips, start=1):
                name = job.name if len(slips) == 1 else f"{job.name} {number}/{len(slips)}"
                self.handoff.send(slip, name, job.queue)
        except QueueFull:
            _LOGGER.warning("job %s '%s': the queue in Home Assistant is full", job.id, job.name)
            return self._fail(job, ipp.NOT_ACCEPTING, say(self.language, "full"), "aborted-by-system")
        except Offline as err:
            _LOGGER.error("handing job %s over failed: %s", job.id, err)
            return self._fail(job, ipp.TEMPORARY_ERROR, say(self.language, "offline"), "aborted-by-system")
        job.state, job.reason = COMPLETED, "job-completed-successfully"
        _LOGGER.info("job %s '%s' handed over, %s rows", job.id, job.name, result.dots.height)
        return ipp.OK, ""

    @staticmethod
    def _fail(job: Job, status: int, message: str, reason: str) -> tuple[int, str]:
        job.state, job.reason, job.message = ABORTED, reason, message
        return status, message

    def healthy(self) -> tuple[bool, str]:
        if shutil.which("tesseract") is None:
            return False, "tesseract missing"
        return True, "ok"


def handle(service: Service, request: ipp.Request, queue: str = "print") -> bytes:
    operation = request.operation
    if not request.attributes.get("attributes-charset") or not request.attributes.get("attributes-natural-language"):
        return ipp.response(request, ipp.BAD_REQUEST, "attributes-charset and attributes-natural-language are required")
    user = str(request.first("requesting-user-name", ""))
    if operation == ipp.GET_PRINTER_ATTRIBUTES:
        unique = service.unique if queue == "print" else uuid.uuid5(service.unique, "label")
        attributes = printer_attributes(service.uris[queue], unique, int(time.monotonic() - service.started),
                                        service.admin, queue, service.language)
        return ipp.response(request, ipp.OK, groups=[(ipp.PRINTER, attributes)])
    if operation == ipp.VALIDATE_JOB:
        return ipp.response(request, ipp.OK) if _format_ok(request) else _bad_format(request)
    if operation == ipp.PRINT_JOB:
        if not _format_ok(request):
            return _bad_format(request)
        job = service.new_job(str(request.first("job-name", "")), user, queue=queue)
        status, message = service.run(job, request.document, str(request.first("document-format", "")))
        return ipp.response(request, status, message, [(ipp.JOB, service.job_group(job))])
    if operation == ipp.CREATE_JOB:
        job = service.new_job(str(request.first("job-name", "")), user, queue=queue)
        return ipp.response(request, ipp.OK, groups=[(ipp.JOB, service.job_group(job))])
    job = service.jobs.get(_job_id(request))
    if operation == ipp.SEND_DOCUMENT:
        if job is None:
            return ipp.response(request, ipp.NOT_FOUND, "no such job")
        if not _format_ok(request):
            return _bad_format(request)
        status, message = service.run(job, request.document, str(request.first("document-format", "")))
        return ipp.response(request, status, message, [(ipp.JOB, service.job_group(job))])
    if operation == ipp.GET_JOB_ATTRIBUTES:
        if job is None:
            return ipp.response(request, ipp.NOT_FOUND, "no such job")
        return ipp.response(request, ipp.OK, groups=[(ipp.JOB, service.job_group(job))])
    if operation == ipp.CANCEL_JOB:
        if job is None:
            return ipp.response(request, ipp.NOT_FOUND, "no such job")
        if job.state in (PENDING, PROCESSING):
            job.state, job.reason = CANCELED, "job-canceled-by-user"
        return ipp.response(request, ipp.OK)
    if operation == ipp.GET_JOBS:
        groups = [(ipp.JOB, service.job_group(j)) for j in list(service.jobs.values())[-10:]]
        return ipp.response(request, ipp.OK, groups=groups)
    return ipp.response(request, ipp.OPERATION_NOT_SUPPORTED, "operation not supported")


def _format_ok(request: ipp.Request) -> bool:
    fmt = request.first("document-format")
    return fmt is None or str(fmt) in FORMATS


def _bad_format(request: ipp.Request) -> bytes:
    return ipp.response(request, ipp.DOCUMENT_FORMAT_NOT_SUPPORTED, "document format not supported")


def _job_id(request: ipp.Request) -> int:
    job_id = request.first("job-id")
    if isinstance(job_id, int):
        return job_id
    uri = str(request.first("job-uri", ""))
    tail = uri.rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else -1


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "iPrint"
    sys_version = ""
    service: Service
    timeout = 120

    def log_message(self, fmt: str, *args) -> None:
        _LOGGER.debug(fmt, *args)

    def _body(self) -> bytes | None:
        """Plain or chunked: clients use both. None when it is larger than any page has reason to be."""
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            out = bytearray()
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline().strip():
                        pass
                    return bytes(out)
                if len(out) + size > MAX_BODY:
                    return None
                out += self.rfile.read(size)
                self.rfile.readline()
        length = int(self.headers.get("Content-Length", 0) or 0)
        return None if length > MAX_BODY else self.rfile.read(length)

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _choice_token(self) -> str | None:
        parts = self.path.split("?")[0].strip("/").split("/")
        return parts[1] if len(parts) == 2 and parts[0] == "wahl" else None

    def _picture_path(self) -> tuple[str, bool] | None:
        """/bild/<token> or /bild/<token>/vorschau."""
        parts = self.path.split("?")[0].strip("/").split("/")
        if len(parts) in (2, 3) and parts[0] == "bild" and (len(parts) == 2 or parts[2] == "vorschau"):
            return parts[1], len(parts) == 3
        return None

    def _query(self) -> dict:
        from urllib.parse import parse_qs

        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        return {k: v[0] for k, v in parse_qs(query).items()}

    def do_GET(self) -> None:  # noqa: N802
        picture = self._picture_path()
        if picture is not None:
            token, preview = picture
            waiting = self.service.choices.get(token)
            language = self.service.language
            if waiting is None or waiting.picture is None:
                self._send(404, "text/html; charset=utf-8", message_page(say(language, "gone"), language).encode())
            elif preview:
                dots = editor.apply(waiting.picture, editor.Settings.parse(self._query()))
                self._send(200, "image/png", editor.preview_png(dots))
            else:
                self._send(200, "text/html; charset=utf-8", editor.page(token, waiting.label, language).encode())
            return
        token = self._choice_token()
        if token is not None:
            waiting = self.service.choices.get(token)
            language = self.service.language
            body = page(token, waiting, language) if waiting else message_page(say(language, "gone"), language)
            self._send(200 if waiting else 404, "text/html; charset=utf-8", body.encode())
            return
        if self.path == "/healthz":
            ok, why = self.service.healthy()
            self._send(200 if ok else 503, "text/plain", why.encode())
        else:
            # not named "page": that name is the choice page function, and a local of the same name hid it from the
            # whole method, so every choice page failed (found live on 08.11.2026)
            home = "<!doctype html><meta charset=utf-8><title>iPrint</title><h1>iPrint PHOMEMO</h1><p>Network printer. " \
                   f"Add <code>{self.service.uri}</code>, or look for it in your print dialog.</p>"
            self._send(200, "text/html; charset=utf-8", home.encode())

    def do_POST(self) -> None:  # noqa: N802
        picture = self._picture_path()
        if picture is not None:
            from urllib.parse import parse_qs

            length = min(int(self.headers.get("Content-Length", 0) or 0), 4096)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8", "replace")).items()}
            ok, text = self.service.edit(picture[0], form)
            self._send(200 if ok else 409, "text/html; charset=utf-8",
                       message_page(text, self.service.language).encode())
            return
        token = self._choice_token()
        if token is not None:
            from urllib.parse import parse_qs

            length = min(int(self.headers.get("Content-Length", 0) or 0), 4096)
            form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            ok, text = self.service.decide(token, form.get("way", [""])[0], form.get("captions", [""])[0] == "1")
            self._send(200 if ok else 404, "text/html; charset=utf-8",
                       message_page(text, self.service.language).encode())
            return
        try:
            body = self._body()
        except ValueError:
            self.close_connection = True
            self._send(400, "text/plain", b"bad request")
            return
        if body is None:
            self.close_connection = True
            self._send(413, "text/plain", b"too large")
            return
        try:
            request = ipp.parse_request(body)
        except ValueError as err:
            self._send(400, "text/plain", str(err).encode())
            return
        queue = "label" if self.path.rstrip("/").endswith("/label") else "print"
        self._send(200, "application/ipp", handle(self.service, request, queue))


def make_server(service: Service, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"service": service})
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    server.daemon_threads = True
    return server
