"""Announce the printer on the network: this is how iPhones and Android phones find it without any setup."""
from __future__ import annotations

import socket
import uuid

from zeroconf import ServiceInfo, Zeroconf

from .printer import FORMATS, NAME_SHOWN, SHOWN, URF


def announce(address: str, port: int, unique: uuid.UUID, admin: str, language: str = "en") -> Zeroconf:
    properties = {
        "txtvers": "1", "qtotal": "1", "rp": "ipp/print", "ty": "iPrint PHOMEMO", "product": "(iPrint PHOMEMO)",
        "note": "beta", "adminurl": admin, "pdl": ",".join(FORMATS[:5]), "URF": URF, "Color": "F", "Duplex": "F",
        "Copies": "F", "Scan": "F", "Fax": "F", "PaperMax": "<legal-A4", "kind": "roll,receipt", "priority": "50",
        "UUID": str(unique),
    }
    zc = Zeroconf(interfaces=[address])
    label = {**properties, "rp": "ipp/label", "ty": "iPrint PHOMEMO shipping label", "PaperMax": "legal-A4",
             "UUID": str(uuid.uuid5(unique, "label"))}
    label_name = SHOWN["label"].get(language, SHOWN["label"]["en"])
    # The library allows one type per instance name. iPhones browse the _universal subtype, everything else plain _ipp,
    # and each browser only ever sees its own entry, so two names do not show up as two printers in one list.
    for props, shown in ((properties, NAME_SHOWN), (label, label_name)):
        for type_, name in (("_universal._sub._ipp._tcp.local.", shown), ("_ipp._tcp.local.", f"{shown} IPP")):
            zc.register_service(ServiceInfo(type_=type_, name=f"{name}._ipp._tcp.local.", port=port, properties=props,
                                            addresses=[socket.inet_aton(address)], server="iprint-phomemo.local."))
    return zc
