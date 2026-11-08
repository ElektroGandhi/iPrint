"""What this printer says about itself. Clients decide from this alone whether and how they print."""
from __future__ import annotations

import uuid

from . import __version__
from .ipp import (
    BEG_COLLECTION,
    BOOLEAN,
    CHARSET,
    ENUM,
    INTEGER,
    KEYWORD,
    LANGUAGE,
    MIME,
    NAME,
    RANGE,
    RESOLUTION,
    Resolution,
    TEXT,
    URI,
    URI_SCHEME,
    attribute,
    collection,
)

NAME_SHOWN = "iPrint PHOMEMO"   # no model in the name (asked for 08.11.2026)
FORMATS = ["application/pdf", "image/jpeg", "image/png", "image/urf", "image/pwg-raster", "application/octet-stream"]
URF = "V1.4,CP1,W8,SRGB24,RS203,DM1"
DPI = 203
# width, length in hundredths of a mm; keyword. 48 mm is what can be printed of the 53 mm roll.
MEDIA = [(4800, 10000, "oe_t02-short_48x100mm"), (4800, 20000, "oe_t02-long_48x200mm")]
# The label queue offers the carriers' own paper sizes on purpose: a client that saw only 48 mm would shrink the label
# before sending it, and shrinking is exactly what makes Code 128 unreadable.
LABEL_MEDIA = [(21000, 29700, "iso_a4_210x297mm"), (10500, 14800, "iso_a6_105x148mm"),
               (10160, 15240, "na_index-4x6_4x6in"), (14800, 21000, "iso_a5_148x210mm")]
QUEUES = {"print": ("iPrint_PHOMEMO", MEDIA), "label": ("iPrint_PHOMEMO_Label", LABEL_MEDIA)}
SHOWN = {"print": {"de": "iPrint PHOMEMO", "en": "iPrint PHOMEMO"},
         "label": {"de": "iPrint PHOMEMO Versandetikett", "en": "iPrint PHOMEMO shipping label"}}


def media_col(size: tuple[int, int, str], name: str = "media-col-default", first: bool = True) -> bytes:
    return collection(name, [
        (BEG_COLLECTION, "media-size", [(INTEGER, "x-dimension", size[0]), (INTEGER, "y-dimension", size[1])]),
        (INTEGER, "media-bottom-margin", 0), (INTEGER, "media-left-margin", 0),
        (INTEGER, "media-right-margin", 0), (INTEGER, "media-top-margin", 0),
        (KEYWORD, "media-source", "main"), (KEYWORD, "media-type", "stationery"),
    ], first)


def printer_attributes(uri: str, unique: uuid.UUID, up_seconds: int, admin: str, queue: str = "print",
                       language: str = "en") -> bytes:
    printer_name, media = QUEUES[queue]
    shown = SHOWN[queue].get(language, SHOWN[queue]["en"])
    out = b""
    for tag, name, value in [
        (URI, "printer-uri-supported", uri),
        (KEYWORD, "uri-security-supported", "none"),
        (KEYWORD, "uri-authentication-supported", "none"),
        (NAME, "printer-name", printer_name),
        (TEXT, "printer-info", shown),
        (TEXT, "printer-make-and-model", "iPrint PHOMEMO"),
        (TEXT, "printer-location", ""),
        (URI, "printer-uuid", f"urn:uuid:{unique}"),
        (ENUM, "printer-state", 3),
        (KEYWORD, "printer-state-reasons", "none"),
        (BOOLEAN, "printer-is-accepting-jobs", True),
        (INTEGER, "queued-job-count", 0),
        (INTEGER, "printer-up-time", max(1, up_seconds)),
        (KEYWORD, "ipp-versions-supported", ["1.1", "2.0"]),
        (ENUM, "operations-supported", [0x0002, 0x0004, 0x0005, 0x0006, 0x0008, 0x0009, 0x000A, 0x000B]),
        (BOOLEAN, "multiple-document-jobs-supported", False),
        (KEYWORD, "multiple-operation-time-out-action", "abort-job"),
        (INTEGER, "multiple-operation-time-out", 60),
        (CHARSET, "charset-configured", "utf-8"),
        (CHARSET, "charset-supported", "utf-8"),
        (LANGUAGE, "natural-language-configured", "en"),
        (LANGUAGE, "generated-natural-language-supported", "en"),
        (MIME, "document-format-default", "application/octet-stream"),
        (MIME, "document-format-supported", FORMATS),
        (KEYWORD, "compression-supported", "none"),
        (BOOLEAN, "pdl-override-supported", False),
        (BOOLEAN, "color-supported", False),
        (KEYWORD, "print-color-mode-default", "monochrome"),
        (KEYWORD, "print-color-mode-supported", "monochrome"),
        (KEYWORD, "output-mode-default", "monochrome"),
        (KEYWORD, "output-mode-supported", "monochrome"),
        (KEYWORD, "sides-default", "one-sided"),
        (KEYWORD, "sides-supported", "one-sided"),
        (INTEGER, "copies-default", 1),
        (RANGE, "copies-supported", (1, 1)),
        (ENUM, "finishings-default", 3),
        (ENUM, "finishings-supported", 3),
        (ENUM, "orientation-requested-default", 3),
        (ENUM, "orientation-requested-supported", [3, 4, 5, 6]),
        (ENUM, "print-quality-default", 4),
        (ENUM, "print-quality-supported", [4]),
        (RESOLUTION, "printer-resolution-default", Resolution(DPI)),
        (RESOLUTION, "printer-resolution-supported", Resolution(DPI)),
        (RESOLUTION, "pwg-raster-document-resolution-supported", Resolution(DPI)),
        (KEYWORD, "pwg-raster-document-type-supported", ["sgray_8", "srgb_8"]),
        (KEYWORD, "pwg-raster-document-sheet-back", "normal"),
        (KEYWORD, "urf-supported", URF.split(",")),
        (KEYWORD, "media-default", media[0][2]),
        (KEYWORD, "media-ready", [m[2] for m in media]),
        (KEYWORD, "media-supported", [m[2] for m in media]),
        (KEYWORD, "media-source-supported", "main"),
        (KEYWORD, "media-type-supported", "stationery"),
        (INTEGER, "media-bottom-margin-supported", 0),
        (INTEGER, "media-left-margin-supported", 0),
        (INTEGER, "media-right-margin-supported", 0),
        (INTEGER, "media-top-margin-supported", 0),
        (KEYWORD, "media-col-supported", ["media-size", "media-bottom-margin", "media-left-margin", "media-right-margin",
                                          "media-top-margin", "media-source", "media-type"]),
        (KEYWORD, "job-creation-attributes-supported", ["copies", "media", "media-col", "orientation-requested",
                                                        "print-color-mode", "print-quality", "sides", "print-scaling"]),
        (KEYWORD, "print-scaling-default", "auto"),
        (KEYWORD, "print-scaling-supported", ["auto", "fit", "fill", "none"]),
        (KEYWORD, "print-content-optimize-default", "auto"),
        (KEYWORD, "print-content-optimize-supported", ["auto"]),
        (TEXT, "printer-firmware-string-version", __version__),
        (URI, "printer-more-info", admin),
    ]:
        out += attribute(tag, name, value)
    out += media_col(media[0])
    for index, size in enumerate(media):
        out += media_col(size, "media-col-database", index == 0)
    for index, size in enumerate(media):
        out += media_col(size, "media-col-ready", index == 0)
    return out
