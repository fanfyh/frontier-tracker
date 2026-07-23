#!/usr/bin/env python3
"""Shared bootstrap: load `.env` from the project root into os.environ.

Imported as the first statement by every pipeline script so API keys no longer
have to be exported manually in each shell session. `.env` values do NOT
override variables already present in the real environment (override=False),
mirroring the PaperEcho convention: shell/secret-store always wins over `.env`.

`python-dotenv` is optional — if it isn't installed, scripts silently fall back
to reading the real environment (the original behavior), so this never blocks a
run that previously worked.
"""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env", override=False)
except ImportError:
    pass

# macOS python.org builds ship without a configured OpenSSL CA bundle, so
# urllib-based fetches (scan_recent_papers.py) fail SSL verification while
# `requests`/pyalex still work (they bundle certifi). Point the stdlib ssl
# module at certifi's bundle so HTTPS works regardless of how the host Python
# was installed. Existing env values win (setdefault), so a custom CA bundle
# is always respected.
if not (os.environ.get("SSL_CERT_FILE") and os.environ.get("REQUESTS_CA_BUNDLE")):
    try:
        import certifi

        _bundle = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", _bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", _bundle)
    except ImportError:
        pass
