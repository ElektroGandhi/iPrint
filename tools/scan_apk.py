#!/usr/bin/env python3
"""Count what an Android app ships. Standard library only; reads the APK as a zip and never runs anything from it.

    python3 tools/scan_apk.py Phomemo_4.1.1.apk

The APK is not part of this repository. Get your own copy to check docs/WHY.md. Finding code in an app proves that the
code is there, not that it runs on every device or for every user.
"""
import hashlib
import re
import sys
import zipfile

GROUPS = {
    "Tracking, Umeng": rb"Lcom/umeng/[^;\x00]+;",
    "Tracking, SensorsData": rb"Lcom/sensorsdata/[^;\x00]+;",
    "Tracking, Firebase Analytics": rb"Lcom/google/firebase/analytics/[^;\x00]+;",
    "Billing, Google Play": rb"Lcom/android/billingclient/[^;\x00]+;",
    "Payment, the vendor's own": rb"Lcom/quyin/payment/[^;\x00]+;",
    "Advertising, the vendor's own": rb"Lcom/(?:quyin/advert|quin/bizuikit/splash/advertisement)/[^;\x00]+;",
}
WORDS = [b"AI_DRAWING", b"AI_TATTOO", b"AI_STICKER", b"AI_FILTER", b"AI_BLENDING",
         b"https://aip.baidubce.com/rest/2.0/ocr/", b"VipBenefitsActivity", b"AdvertDetailActivity",
         b"CreditsDetailActivity"]


def main(path: str) -> None:
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    archive = zipfile.ZipFile(path)
    dex = [archive.read(n) for n in archive.namelist() if n.endswith(".dex")]
    print(f"{path}\n  sha256 {digest}\n  {sum(len(d) for d in dex) / 1e6:.0f} MB of code in {len(dex)} dex files\n")
    print("Distinct class names")
    for label, pattern in GROUPS.items():
        names = {m for d in dex for m in re.findall(pattern, d)}
        print(f"  {len(names):6}  {label}")
    print("\nStrings")
    for word in WORDS:
        print(f"  {'found  ' if any(word in d for d in dex) else 'absent '} {word.decode()}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
