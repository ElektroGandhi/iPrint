# Phomemo T02 for Home Assistant

Print to a Phomemo T02 thermal printer from Home Assistant, without the app or a cloud. Local, over Bluetooth classic.

*Ideas by BLOTTO, vibed by OPUS.* [Deutsch](README.de.md)

## What you get

- `notify.send_message` prints: any automation that can notify can print.
- `phomemo.print_text`: word-wrapped text with an optional title, size and darkness.
- `phomemo.print_image`: scales a picture to the paper width and dithers it.
- `phomemo.feed` and buttons for feeding paper and printing a test page.
- Sensors for battery, lid and paper, and a darkness setting.

A job is only reported as done when the printer says so. An open lid or an empty roll raises an error instead of
losing the job.

## Requirements

- A Bluetooth adapter that does classic Bluetooth (BR/EDR), on the machine running Home Assistant. **ESPHome Bluetooth
  proxies do not work**: they only carry BLE.
- Home Assistant OS or another install where the container shares the host network. Measured on HA OS.

## Install

Copy `custom_components/phomemo` into your `config/custom_components`, or add this repository to HACS as a custom
repository, then restart Home Assistant.

Add the integration under **Settings → Devices & services** and enter the printer's address. Home Assistant's discovery
only sees BLE, so it cannot find the printer. To get the address, switch the printer on and run this on the HA host:

```
bluetoothctl scan bredr
```

Look for a device named `T02`. No pairing is needed.

## Use

```yaml
action: notify.send_message
target:
  entity_id: notify.t02_print
data:
  title: Shopping
  message: Milk, eggs, butter
```

```yaml
action: phomemo.print_image
data:
  path: /config/www/label.png
```

`print_image` only reads from folders listed in
[`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs).
Jobs are limited to 4000 rows (about 50 cm), so a runaway automation cannot empty the roll.

## Limits

- Only tested on a T02 with firmware 1.0.0. Other Phomemo models may use other commands.
- Sensors show *unavailable* while the printer is off. That is normal.
- A status check connects to the printer every 10 minutes.

The protocol is documented in [docs/PROTOCOL.md](docs/PROTOCOL.md). MIT licensed. Includes DejaVu Sans, see `custom_components/phomemo/fonts/LICENSE`. Not affiliated with Phomemo.
