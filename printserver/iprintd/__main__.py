"""Start: python -m iprintd. Settings come from the environment, see printserver/README.md."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import uuid

from .handoff import Handoff
from .mdns import announce
from .server import Service, make_server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    address = os.environ["IPRINT_ADDRESS"]
    port = int(os.environ.get("IPRINT_PORT", "631"))
    language = os.environ.get("IPRINT_LANGUAGE", "en")
    url = Path(os.environ["IPRINT_WEBHOOK_FILE"]).read_text().strip()
    # Stable from the address: clients recognise the printer again after an update.
    unique = uuid.uuid5(uuid.NAMESPACE_URL, f"iprint:{address}")
    ask = os.environ.get("IPRINT_ASK", "0").strip().lower() in ("1", "true", "yes", "on")
    service = Service(Handoff(url), address, port, unique, language, ask)
    server = make_server(service, port)
    zeroconf = announce(address, port, unique, service.admin, language)
    logging.getLogger("iprintd").info("listening on %s, questions %s", service.uri, "on" if ask else "off")
    try:
        server.serve_forever()
    finally:
        zeroconf.unregister_all_services()
        zeroconf.close()


if __name__ == "__main__":
    main()
