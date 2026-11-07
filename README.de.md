# Phomemo T02 für Home Assistant

Aus Home Assistant auf einem Phomemo-T02-Thermodrucker drucken, ohne App und ohne Cloud. Lokal, über klassisches Bluetooth.

*Ideas by BLOTTO, vibed by OPUS.* [English](README.md)

## Was es kann

- `notify.send_message` druckt: Jede Automation, die benachrichtigen kann, kann auch drucken.
- `phomemo.print_text`: Text mit Zeilenumbruch, wahlweise mit Überschrift, Größe und Druckstärke.
- `phomemo.print_image`: skaliert ein Bild auf Papierbreite und rastert es.
- `phomemo.feed` und Knöpfe für Papiervorschub und Testseite.
- Sensoren für Akku, Klappe und Papier, dazu eine Einstellung für die Druckstärke.

Ein Druck gilt erst als fertig, wenn der Drucker das meldet. Bei offener Klappe oder leerer Rolle kommt eine Fehlermeldung,
statt dass der Druck verloren geht.

## Voraussetzungen

- Ein Bluetooth-Adapter mit klassischem Bluetooth (BR/EDR) an dem Rechner, auf dem Home Assistant läuft.
  **ESPHome-Bluetooth-Proxys gehen nicht**: Sie leiten nur BLE weiter.
- Home Assistant OS oder eine andere Installation, bei der der Container das Host-Netz teilt. Gemessen auf HA OS.

## Einrichten

`custom_components/phomemo` nach `config/custom_components` kopieren oder dieses Repository in HACS als benutzerdefiniertes
Repository eintragen, dann Home Assistant neu starten.

Unter **Einstellungen → Geräte & Dienste** die Integration hinzufügen und die Adresse des Druckers eintragen. Die Suche von
Home Assistant sieht nur BLE und findet den Drucker deshalb nicht. Für die Adresse den Drucker einschalten und auf dem HA-Host
ausführen:

```
bluetoothctl scan bredr
```

Gesucht ist ein Gerät namens `T02`. Eine Kopplung ist nicht nötig.

## Benutzen

```yaml
action: notify.send_message
target:
  entity_id: notify.t02_drucken
data:
  title: Einkauf
  message: Milch, Eier, Butter
```

```yaml
action: phomemo.print_image
data:
  path: /config/www/etikett.png
```

`print_image` liest nur aus Ordnern, die in
[`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs) stehen.
Ein Druck ist auf 4000 Zeilen begrenzt (etwa 50 cm), damit eine fehlgeleitete Automation nicht die ganze Rolle verbraucht.

## Grenzen

- Nur getestet mit einem T02 mit Firmware 1.0.0. Andere Phomemo-Modelle nutzen eventuell andere Befehle.
- Die Sensoren stehen auf *nicht verfügbar*, solange der Drucker aus ist. Das ist normal.
- Für den Status verbindet sich die Integration alle 10 Minuten mit dem Drucker.

Das Protokoll steht in [docs/PROTOCOL.md](docs/PROTOCOL.md). MIT-Lizenz. Enthält DejaVu Sans, siehe `custom_components/phomemo/fonts/LICENSE`. Keine Verbindung zu Phomemo.
