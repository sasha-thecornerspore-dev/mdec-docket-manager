# Third-Party Components

MDEC Docket Manager is MIT licensed (see [LICENSE](../LICENSE)). The **standalone
builds** — the installer and the portable zip attached to each release — are
frozen with PyInstaller and therefore redistribute the Python interpreter and
the libraries below, each under its own licence.

Installing from source with `pip` redistributes nothing: pip fetches these from
PyPI under their own terms. This file describes the release artefacts.

Derived by inspecting a built tree, not the manifests:
`build_dist/MDECDocketManager/_internal/`. That distinction matters — a wheel
that is permissively licensed can carry a differently-licensed binary inside it,
which is exactly how an LGPL FFmpeg reached four public releases of a sibling
project before anyone looked in the build.

## Not present, and deliberately so

`tools/mdec.spec` excludes `ocrmypdf` and `pikepdf`. That keeps **Ghostscript
(AGPL-3.0)** out of the shipped binary: OCR is opt-in, and when enabled it
invokes a system Ghostscript and Tesseract that the user installed themselves,
out of process. The exclusion is a licence control as much as a weight control —
do not remove it without deciding what replaces it.

There is no FFmpeg, no OpenCV, and no MuPDF in this build.

**Chromium is not bundled.** Playwright downloads its browser on first use into
the user's own Playwright cache. The release archives do not contain it.

## Apache License 2.0

| Component | Notes |
| --- | --- |
| Playwright (`playwright` 1.61.0) | Browser automation. Ships a Node driver; not the browser itself. |
| `cryptography` 49.0.0 | Dual Apache-2.0 / BSD-3-Clause. Bundles OpenSSL (Apache-2.0). |
| `bcrypt` | |
| `tzdata` | Packaging of the IANA database, which is itself public domain. |

## MIT

`anthropic` 0.120.0 · `keyring` 25.7.0 · `mcp` 1.28.1 · `pydantic` 2.13.4 and
`pydantic-core` · `jsonschema` 4.26.0 and `jsonschema-specifications` ·
`attrs` 26.1.0 · `pdfminer.six` 20260107 · `charset-normalizer` · `greenlet` ·
`httptools` · `watchfiles` · `jiter` · `rpds-py` · `PyYAML` · `setuptools` ·
`imap-tools`

## BSD (2- or 3-clause)

`uvicorn` 0.51.0 · `websockets` 16.1.1 · `numpy` · `click` 8.4.2 ·
`markupsafe` 3.0.3 · `werkzeug` 3.1.8 · `itsdangerous` 2.2.0 · `zstandard` ·
`pypdfium2` and `pypdfium2_raw`, which embed **PDFium** (BSD-3-Clause)

## Mozilla Public License 2.0

| Component | Obligation |
| --- | --- |
| `certifi` | The MPL requires the source of this component stay available. It is unmodified and obtainable from <https://github.com/certifi/python-certifi>. |

## Other

| Component | Licence |
| --- | --- |
| Pillow (`PIL`) | MIT-CMU |
| Python (the embedded interpreter) | Python Software Foundation License |
| Tcl/Tk (`tcl8`, `_tcl_data`, `_tk_data`) | Tcl/Tk License (BSD-style) — embedded for the folder picker |
| pywin32 (`win32`, `pywin32_system32`) | PSF-style — Windows builds only, for the keyring backend |
| PyInstaller | GPL-2.0-or-later **with** the bootloader exception, which expressly permits distributing frozen applications under other licences |

## Keeping this file true

Regenerate it against a built tree whenever a dependency is added or the spec's
`excludes` change — not against `requirements.txt`. A manifest-only check cannot
see what a wheel carries inside it, and that is the failure mode this file
exists to prevent.
