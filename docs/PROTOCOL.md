# Phomemo T02 protocol

How the T02 talks, read from the Android app (`com.quyin.phomemo` 4.1.1) and checked against a real printer
(firmware 1.0.0). **Measured** means seen on the device; **app** means read from the code only and not yet seen.

## Transport

Bluetooth classic, Serial Port Profile (`00001101-0000-1000-8000-00805F9B34FB`), RFCOMM channel 1. **Measured:** connects
in 1.3 s with no pairing. The device advertises as `T02`, class `0x00100680` (printer).

**Keep the connection open.** Measured: one held connection answered 12 of 12 questions over 6 minutes and printed at
once. After a disconnect the printer refuses new connections with `EBUSY`, `EHOSTDOWN` or a timeout, sometimes for more
than 30 s, and reconnecting every few seconds succeeded only 3 times in 15. An answer takes 0.4 to 4.8 s, and answers to
several questions can arrive together, so read a stream of frames instead of expecting one answer per question.

Home Assistant's Bluetooth integration is BLE-only, and the T02's name does not appear in a BLE scan. **Measured:** a raw
`AF_BLUETOOTH` socket works inside the Home Assistant container on HA OS, which is what this integration uses. The app
also knows a BLE path (`0000FF02`), but only uses it for its Wi-Fi printer family, not for the T02.

## Printing

| Step | Bytes | |
|---|---|---|
| Init | `1B 40` | measured |
| Darkness | `1F 11 02 LL` + `1F 11 37 EE` | measured with `04`/`64` |
| Paper type | `1F 11 0B` (`26`, `38` for other paper) | measured with `0B` |
| Compression off | `1F 11 35 00` | measured |
| Image header | `1D 76 30 00 wL wH hL hH` | measured |
| Image data | `w*h` bytes | measured |
| Feed, twice | `1B 64 02` | measured |
| End of job | printer answers `1A 0F 0C` | measured, 3.9 s for 160 rows |

`w` is bytes per row, always 48 (384 dots at 203 dpi, 48 mm). `h` is rows, little-endian. One bit per dot, leftmost dot
in the high bit, 1 = black. Darkness: `LL`/`EE` = `01/64`, `02/64`, `04/64`, `04/96`.

## Asking

All answers are `1A`-frames. A single answer can carry a second, unrequested frame.

| Ask | Answer | Meaning | |
|---|---|---|---|
| `1F 11 12` | `1A 05 xx` | `98` lid closed, `99` open | measured `98` |
| `1F 11 11` | `1A 06 xx` | `88` no paper, otherwise paper | measured `89` |
| `1F 11 08` | `1A 04 xx` | battery %, or `A1`/`A2`/`A3` = warning 10/5/3 % | measured |
| `1F 11 07` | `1A 07 a b c` | firmware | measured |
| `1F 11 09` | `1A 08` + 15 bytes | serial number | measured |
| `1F 11 0E` | `1A 09 xx` | auto-off, `xx` * 5 min | measured `0C` = 60 min |
| `1F 11 38` | `1A 17 xx` | chip, `3`/`7` = Jieli | measured `03` |
| — | `1A 03 xx` | `A8` normal, `A9` overheated | app |
| — | `1A 0B B8` | job cancelled | app |
| — | `1A 35 xx` | `02` charging | app |

`1F 11 63`, `5E`, `56`, `51` got no answer from this printer.

## Setting

| Command | Meaning | |
|---|---|---|
| `1B 4E 07 nn` | auto-off, `nn` * 5 min | app, never sent. It looks like the setter of `1F 11 0E`. |

## Sleep

After a while without contact the printer stops answering. **Measured:** the connection still succeeds, but no question gets
an answer, not even after `1B 40`. Switching it off and on brings it back. One sign of this state was a user seeing it
switched off while the radio still accepted connections.

**Battery while charging:** the reading jumped from 4 % to 73 % within minutes of plugging in. It looks like it follows
the voltage, so do not read it as a true level while charging.
