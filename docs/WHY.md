# Why iPrint exists

The T02 is a simple device. It takes 48 bytes per row of dots over a serial Bluetooth link, and a handful of commands
around them. Officially, the only way to use it is the vendor's phone app, and that app is a lot more than a printer driver.

**Everything below can be checked.** It comes from the Android app `com.quyin.phomemo` version 4.1.1 (`sha256 0cd3fa6b…a5d8`),
read without running it. To count for yourself:

```
python3 tools/scan_apk.py Phomemo_4.1.1.apk
```

> Finding code in an app proves that the code is there. It does not prove that every part runs on every phone, or for
> every user. This page describes what ships with the app, not what it does on your device.

## Size

| | Phomemo app 4.1.1 | iPrint 0.1 |
|---|---|---|
| Download | 134 MB, plus a device-specific part | about 1 MB, most of it the font |
| Code | 81 MB in 18 dex files | under 1000 lines of Python |

## What ships with the app

| What | Evidence | Count |
|---|---|---|
| Advertising, the vendor's own system | `com.quin.bizuikit.splash.advertisement`, `com.quyin.advert`, including `AdvertDetailActivity` | 156 class names |
| Paid features | `com.quyin.payment`, including `VipBenefitsActivity`; `CreditsDetailActivity` | 33 class names |
| Google Play billing | `com.android.billingclient`, permission `BILLING` | 198 class names |
| Tracking, Umeng | `com.umeng` | 423 class names |
| Tracking, SensorsData | `com.sensorsdata` | 669 class names |
| Tracking, Firebase Analytics | `com.google.firebase.analytics` | 8 class names |
| AI features | `AI_DRAWING`, `AI_TATTOO`, `AI_STICKER`, `AI_FILTER`, `AI_BLENDING` | strings |
| AI text recognition by Baidu | `https://aip.baidubce.com/rest/2.0/ocr/` | endpoints |

## What the app asks for

Printing over Bluetooth needs the Bluetooth permissions. The app also requests these, among others:

| Permission | Plain meaning |
|---|---|
| `RECORD_AUDIO` | microphone |
| `CAMERA` | camera |
| `ACCESS_FINE_LOCATION` | precise location |
| `READ_PHONE_STATE` | phone status |
| `ACCESS_ADSERVICES_AD_ID` | advertising ID |
| `ACCESS_ADSERVICES_ATTRIBUTION` | ad attribution |

Android 11 and older also require a location permission to scan for Bluetooth devices, so that one has an innocent
explanation. A camera can also be used to scan a code, and a microphone for a voice feature. The list shows what the app
*can* ask for, not what it does with it.

## What iPrint does instead

iPrint talks to the printer directly and to nothing else. There is no account, no server, no telemetry and no paid tier.
The source is short enough to read in an evening, and [the protocol](PROTOCOL.md) is documented so that anyone can write
their own client.

This project is not affiliated with Phomemo. It exists so that hardware you bought keeps working on your terms.
