"""The door for the optional print server (beta). Closed unless switched on, and it can only print.

A dedicated webhook instead of a Home Assistant token: whoever holds the address can put paper out, nothing more.
Only reachable from the local network.
"""
from __future__ import annotations

import io
import json
import logging

from aiohttp import web
from PIL import Image, UnidentifiedImageError

from homeassistant.components import persistent_notification, webhook
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_NOTIFY, DOMAIN
from .coordinator import IPrintCoordinator, QueueFullError
from .protocol import MAX_ROWS, WIDTH_DOTS

_LOGGER = logging.getLogger(__name__)
# Home Assistant answers 200 to a webhook it does not know, or one refused for coming from outside. So 200 proves nothing,
# and only this status means the job really arrived here.
STATUS_ACCEPTED = 201
EVENT_REFUSED = f"{DOMAIN}_job_refused"
EVENT_QUESTION = f"{DOMAIN}_question"


def _dots(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.width != WIDTH_DOTS or image.height > MAX_ROWS:
            raise ValueError(f"expected a PNG {WIDTH_DOTS} dots wide, up to {MAX_ROWS} rows")
        return image.convert("1", dither=Image.Dither.NONE)


async def _handle(hass: HomeAssistant, coordinator: IPrintCoordinator, request: web.Request) -> web.Response:
    body = await request.read()
    if request.content_type == "application/json" and b'"question"' in body:
        question = json.loads(body)["question"]
        await _ask(hass, coordinator, str(question.get("label", "")), str(question.get("url", "")))
        return web.Response(status=STATUS_ACCEPTED)
    if request.content_type == "application/json":
        data = json.loads(body)
        reason, label = str(data.get("refused", "")), str(data.get("label", ""))
        persistent_notification.async_create(hass, f"{label}: {reason}" if label else reason, "iPrint",
                                             f"{DOMAIN}_refused")
        hass.bus.async_fire(EVENT_REFUSED, {"label": label, "reason": reason})
        return web.Response(status=STATUS_ACCEPTED)
    try:
        image = await hass.async_add_executor_job(_dots, body)
    except (OSError, ValueError, UnidentifiedImageError) as err:
        return web.Response(status=400, text=str(err))
    try:
        kind = "label" if request.headers.get("X-IPrint-Queue") == "label" else "print"
        await coordinator.async_print_image(image, label=request.headers.get("X-IPrint-Label", "Network job"), kind=kind)
    except QueueFullError as err:
        return web.Response(status=507, text=str(err))
    except HomeAssistantError as err:
        _LOGGER.error("Network print job failed: %s", err)
        return web.Response(status=502, text=str(err))
    return web.Response(status=STATUS_ACCEPTED)


async def _ask(hass: HomeAssistant, coordinator: IPrintCoordinator, label: str, url: str) -> None:
    """A job waits for the person: a label choice or a photo to adjust. Tell them where, in HA and on the phone."""
    text = f"„{label}“ wartet: [Jetzt auswählen]({url})" if label else f"Ein Druckauftrag wartet: [Jetzt auswählen]({url})"
    persistent_notification.async_create(hass, text, "iPrint", f"{DOMAIN}_question")
    hass.bus.async_fire(EVENT_QUESTION, {"label": label, "url": url})
    entry = coordinator.config_entry
    for target in [t.strip() for t in entry.options.get(CONF_NOTIFY, "").split(",") if t.strip()]:
        domain, _, service = target.partition(".")
        if domain != "notify" or not hass.services.has_service("notify", service):
            _LOGGER.warning("Notify action %s for print questions does not exist", target)
            continue
        await hass.services.async_call("notify", service, {
            "title": "iPrint", "message": f"„{label}“ wartet auf dich. Antippen zum Auswählen.",
            # iOS opens "url", Android "clickAction"
            "data": {"url": url, "clickAction": url}}, blocking=False)


def async_register(hass: HomeAssistant, coordinator: IPrintCoordinator, webhook_id: str) -> None:
    async def handler(hass_: HomeAssistant, _id: str, request: web.Request) -> web.Response:
        return await _handle(hass_, coordinator, request)

    webhook.async_register(hass, DOMAIN, "iPrint print server", webhook_id, handler, local_only=True,
                           allowed_methods=["POST"])
