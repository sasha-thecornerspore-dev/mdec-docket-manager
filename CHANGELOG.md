# Changelog

Notable changes to MDEC Docket Manager. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

`__version__` lives in `mdec/__init__.py` and is what `/api/ping`,
`/api/status`, and the app's own header report.

## [Unreleased]

### Changed

- **"Auto" now prefers your Claude subscription over a stored API key.** Both
  backends already existed, but auto reached for the key first, so anyone who
  had ever saved one was silently metered for work a Pro/Max plan already
  covers. Forcing `api` or `subscription` still fails loudly rather than
  quietly using the other one — that choice can be deliberate, for cost or for
  keeping documents off a metered API. No change for anyone with only one
  backend configured.

### Added

- The app version is shown in the header, beside the case identity. It was
  already in `/api/status` and nothing displayed it.
- `require_clean_build_env()` refuses to build the installer from a non-venv
  interpreter, or from any environment where an AGPL package such as PyMuPDF
  is importable. PyInstaller bundles what it can import, so freezing from a
  shared interpreter means the binary inherits everything ever installed on the
  machine. See [docs/INSTALL.md](docs/INSTALL.md#building-the-installer).
- Tests for backend selection — seven cases over precedence, fallback, and both
  forced modes. The precedence test fails against the old ordering.
- This changelog.

## [1.6.0] — 2026-08-13 — harvesting works

### Fixed

- Drives your own Chrome rather than a fresh automated browser, and the docket
  parser was corrected against the real page rather than an assumed structure.

## [1.4.0] — 2026-08-13 — hand-off harvesting

### Changed

- **Harvesting is now hand-off.** You reach the docket in your own browser; the
  app takes over from there. This replaced the fully automated path, which the
  portal's bot detection had made unusable.

## [1.3.0] — 2026-08-13 — why checks find nothing

### Added

- Diagnosis for silent checks: distinguishes not-signed-in, a bot-detection
  challenge, and content inside an iframe, and says which one happened.

### Changed

- **Scheduled checks ship disabled.** The portal fingerprints automated
  browsers and serves a challenge, so a fresh install no longer runs a
  scheduler that would reliably trip it. The Settings page explains why.

## [1.2.0] — 2026-08-07 — standalone installer

### Added

- One-click Windows installer and portable zip, desktop icon, release
  packaging, and automatic browser download.

### Fixed

- Playwright path resolution inside the frozen build, which had made the
  standalone installer non-functional.
- Packaging status is reported honestly rather than optimistically.

## [1.1.0] — 2026-07-25

### Added

- Multiple cases, resumable harvests, and a real folder picker.
- Public-release posture and correct clone URLs.

## [1.0.0] — 2026-07-25

### Added

- Initial version: MDEC docket monitor, archive, notes, and Claude analysis.
  Scheduled checks, fingerprint-based new-entry detection, catalog-named
  downloads (`NNNN_YYYYMMDD_Description.pdf`), OCR, and RAG export to a watched
  folder, an HTTP webhook, or a local ChromaDB collection.

[Unreleased]: https://github.com/sasha-thecornerspore-dev/mdec-docket-manager/compare/v1.6.0...HEAD
[1.6.0]: https://github.com/sasha-thecornerspore-dev/mdec-docket-manager/releases/tag/v1.6.0
[1.4.0]: https://github.com/sasha-thecornerspore-dev/mdec-docket-manager/releases/tag/v1.4.0
[1.3.0]: https://github.com/sasha-thecornerspore-dev/mdec-docket-manager/releases/tag/v1.3.0
[1.2.0]: https://github.com/sasha-thecornerspore-dev/mdec-docket-manager/releases/tag/v1.2.0
[1.1.0]: https://github.com/sasha-thecornerspore-dev/mdec-docket-manager/releases/tag/v1.1.0
