# Changelog

Notable changes to MDEC Docket Manager. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

`__version__` lives in `mdec/__init__.py` and is what `/api/ping`,
`/api/status`, and the app's own header report.

## [Unreleased]

## [1.7.0] — 2026-09-23

### Added

- **A completeness audit.** Compares three things that drift apart quietly:
  what the docket offers, what the database recorded, and what is actually in
  the folder. Every entry gets a state — `complete`, `partial`, `missing`,
  `broken`, `view_only` or `none` — and the case gets one plain sentence saying
  whether the archive is whole. On the Dashboard, and at
  `POST /api/actions/audit`.
- **Entries remember how many files their popup offered** (`expected_docs`,
  recorded before the first click, because that is the only moment the count is
  visible). Without it a filing that dropped five of its fourteen attachments
  was indistinguishable from one that was always a single PDF.
- **Duplicate detection that knows what a duplicate means.** Byte-identical
  files are grouped and classified: `entry` (the same entry fetched twice —
  redundant), `cross` (one exhibit genuinely filed under two entries — both
  copies are legitimate), or `unfiled` (not named yet, so ownership is unknown).
  Only `entry` groups can be quarantined, and quarantining moves files into
  `_duplicates` rather than deleting them. Hashing only touches files that
  already share an exact size.
- **Order-dependent renames are labelled.** A repair rename of a legacy folder
  places a repeated title by position alone, so it can be wrong without looking
  wrong. Those renames are now marked `order` and counted separately. In the
  reference folder that is 250 of 308 files.
- `tests/test_audit.py` — the harvest pipeline end to end with only the
  Playwright calls stubbed: numbering, naming, dating, multi-file entries,
  duplicates, adoption, and every audit state. 22 tests.

### Changed

- **Catalog numbers are assigned by filing date, not page order.** The portal
  lists scheduled hearings ahead of docket entries and is not internally sorted,
  so `NNNN` and the `YYYYMMDD` in the filename used to disagree — which meant a
  folder sorted by name was not sorted by time. Entries whose date will not
  parse keep their page position and sort last. Numbering stays stable: only
  new entries are numbered, and they are appended.
- **Every check now ends by saying whether the archive is complete**, in the run
  log and in the response. A run that reported "3 downloaded" while eleven were
  still missing was the quiet half-success this app exists to avoid.

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
- **A release pipeline that can actually publish.** `release.yml` had never run
  for a tag, and five things stood between it and a usable release: it
  downloaded artefacts into the tracked `assets/` directory and would have
  published `mdec.ico`, `mdec-256.png` and `installer_after.txt` as release
  assets; `publish` depended on an unproven macOS leg, so one failing leg meant
  a successful Windows installer was built and never attached; nothing waited
  for the tests, so a tag could publish over a red suite; there was no checksum
  step at all, which matters because the installer is unsigned and the SHA-256
  is therefore the only thing a downloader can check; and the tag-verification
  job ran a bare `python` with no pinned interpreter. Releases now carry
  `SHA256SUMS.txt` with the verification commands inlined in the notes.
- `docs/THIRD-PARTY.md` — what the standalone builds actually redistribute,
  derived from a built tree rather than `requirements.txt`, because a
  permissively licensed wheel can carry a differently licensed binary inside it.
  Also records that the spec's `ocrmypdf`/`pikepdf` exclusion is what keeps AGPL
  Ghostscript out of the binary, and is a licence control rather than only a
  size one.

### Removed

- **The macOS release leg.** It was added unproven and it should not ship. This
  app is Windows-only in source, not merely unsigned elsewhere: the Playwright
  path resolution, the browser-on-disk check, the app window, the data directory
  and the error dialog all assume Windows, so the artefact would have been an
  unsigned, iconless folder that cannot find or install the browser it exists to
  drive — failing quietly while doing it. macOS becomes its own milestone once
  those grow real platform branches.

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
