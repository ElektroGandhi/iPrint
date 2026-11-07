# Contributing

Thank you for helping keep this hardware free.

## Most useful right now

- **Reports from other printers.** Other firmware, other Phomemo models: does it work? What did the printer answer? Open
  an issue with the "New printer" template.
- **Reports from other setups.** Anything that is not Home Assistant OS, or a different Bluetooth adapter.

## Rules for code

- Keep the protocol in `protocol.py` pure: bytes in, bytes out, no I/O.
- A claim about the printer goes in `docs/PROTOCOL.md`, marked as *measured* on a device or as read from the *app*.
- A bug seen on a real printer gets a test that reproduces it, and that test must fail without the fix.
- Never put your printer's address or serial number in an issue, a log or a test.

## Checks

```
pip install pytest pillow
pytest
```

CI also runs `hassfest` and the HACS validation.
