[中文](CHANGELOG.md) | **English**

# Changelog

This project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-11-04

The theme of this release: turning "I built it" into "you can verify it yourself".

### Added

- **`swforge selftest`** - ten checks, each run against the real SolidWorks,
  reading the result back before judging. A failure names which link broke and
  which competitor issue it corresponds to. Exit code works in CI.
  `--only` for one check, `--json` for machine-readable output.

- **BOM** `swforge bom`. Reads the assembly component list, merges repeated
  parts with a counted quantity, and asks `IComponent2` for the material
  rather than opening each part - SolidWorks caps open documents at 8 and
  opening every part would burn that budget. CSV export writes a UTF-8 BOM so
  Excel does not render the Chinese headers as garbage.

- **Document guard** `swforge.guard` for several clients sharing one
  SolidWorks. No cross-process lock - locks around COM are unreliable and a
  crashed holder deadlocks everyone. Each operation verifies the active
  document before and after and re-activates when it was taken. About 1 ms.

- **Generated-source snapshot tests** (11) instead of a full mock. A mock
  simulates SolidWorks as working, while every serious bug in this project was
  found by running against the real thing. These guard the generated C#
  instead: unit conversions, API names, required calls. About a fifth of the
  cost.

- **Documentation site** https://mwdandoms.github.io/swforge/
- **Issue log** `docs/issue-log.md` - a public record with fixed and open items.
- **Roadmap** `docs/roadmap.md` - next steps and exit criteria.

### Fixed

- **The interference detail list was always empty.**
  `GetInterferences` is a property under late binding, not a method; the
  `TypeError` from calling it was swallowed into `None`, so callers got a count
  with nothing behind it. Now returns
  `{"volume_mm3": 4000.0, "components": ["a-1", "b-1"]}`, 0.00% off the
  theoretical 10x20x20.

- **Over-annotation, and wrong values on non-front views.**
  Blanket annotation inserted 22 overlapping dimensions (every type flag
  combination gave 22, so the flags were never the issue); curated mode brings
  it to 9. Separately, extremes were selected by model X/Y, which only holds
  for the front view - a right view's screen horizontal is model Z, so it
  reported 114 for an actual 120. The axis pair now comes from
  `GetOrientationName()`.

- **`swforge --help` crashed on a non-Chinese Windows** (a real user-facing
  bug CI caught).

- **selftest filled the document cap itself**, cascading four later checks
  into failure. Each check now closes what it created.

### Known incomplete

- The **live paths for BOM and the concurrency guard are not yet verified**
  (code and offline tests are done). Unverified features are not claimed as
  working.
- Tolerances, surface finish and GD&T are still not generated.

## [0.9.1] - 2026-11-03

First release published to PyPI. All fixes relative to v0.9.0, no new features.

### Added
- **PyPI publishing** `.github/workflows/publish.yml`: tag to publish, using
  Trusted Publishing (OIDC) so no token is stored in the repository. Three
  pre-publish checks: exactly one wheel, package version matches the tag, and
  the sdist carries docs/.
- **MCP server usability for external agents**: 17 lines of `instructions`
  (the first thing an agent reads), a fix so `serverInfo.version` reports
  swforge's version instead of the MCP SDK's, and multi-client setup in the
  README.
- `tests/test_mcp.py`, six contract tests driving a real stdio session.

### Fixed
- `swforge --help` crashed on a non-Chinese Windows: with a cp1252 stdout,
  printing Chinese raised `UnicodeEncodeError`. Now `errors='replace'` keeps it
  from crashing, and JSON output escapes to `\uXXXX` on a single-byte codec so
  it stays machine-readable.
- `produce()` connected to SolidWorks even for a fresh drawing (regression
  introduced in v0.9.0), dragging pure-logic unit tests into a real connection.
  It now connects only when the target file already exists.
- CI: `package build` failed because PowerShell does not expand `dist/*.whl`;
  switched to bash and to `python -m swforge.cli`.
- CI: the marker check moved from a static text scan to a runtime guard in
  conftest. The static version produced four false positives on tests that only
  exercise parameter validation.

## [0.9.0] - 2026-11-03

### Added
- **Batch drawings** `swforge batch`: one folder of parts becomes a stack of GB-framed
  drawings. Measured 5 parts in 15.7 s; one failure does not sink the batch; existing
  drawings are skipped so an interrupted run resumes.
- **API capability probe** `swforge capabilities --api`: reflects over the locally
  installed Interop library and reports, for 28 risky APIs, whether each exists and its
  highest overload. Measured 0.43 s with a clear verdict. A wrong declared type triggers
  a global scan that reports the real location (`InsertModelAnnotations4` lives on
  `IDrawingDoc`).
- **Overall dimensions now work on revolved parts**: fall back from vertices to edge
  endpoints, then to single-entity dimensions, so cylinders and rings get outer and
  inner diameters (measured flange 120/60, bushing 40/24).
- **CI**: `.github/workflows/tests.yml`, Python 3.10-3.13 matrix running the 106 offline
  tests, plus package build, sdist content check and an `sw` marker guard.
- Tests 124 -> **138** (106 offline + 32 live).

### Fixed
- `produce()` returned `err=1` when the target drawing already existed, because the
  previous drawing was still open and locked the file. It now closes any document
  pointing at the target path first.
- `add_dimensions(overall=True)` referenced an undefined `overall_result` (NameError).
- sdist did not carry `docs/` or `demo/`; `MANIFEST.in` added, 65 files now.
- Batch failed from the 5th part on after hitting SolidWorks' 8-document cap; documents
  are now released after each part.

### Docs
- README gained a "Not yet" section and a three-layer "Verification boundary" table
  (L1 offline / L2 CI / L3 live).
- Chinese and English READMEs kept in sync.

## [0.8.0] - 2026-11-03

### Added
- **Overall dimensions** `dims.py`: explicit overall length/height generated from each
  view's extreme visible vertices (`InsertModelAnnotations4` cannot produce overall
  dimensions and deduplicates across views)
- **Mates** `mates.py`: concentric / coincident with automatic face selection
  (equal-radius cylinders, parallel planes), implemented in C# early binding
- **Exact interference** `interference.py`: body boolean intersection, measured 500.000 mm³
- Tests 111 → **124**

### Fixed
- Interference intersection returning error code 1: `swBodyOperationNonApiBody` —
  document bodies are not API temporary bodies and need `Copy2(False)` first
- Mate success criterion: `swAddMateError_NoError = 1` (not 0)
- Assembly coordinate units: `AddComponent5` expects metres; millimetres were being
  passed, placing parts 60 metres away
- Drawing template selection: now scans by year and prefers Chinese `gb_<paper>.drwdot`
- `_ensure_mm_units` could not read the unit value (`_value()` calling a method that
  requires arguments)

## [0.7.0] - 2026-11-03

### Added
- GB frame and title block (auto-filled material / weight / scale)
- Millimetre unit verification

### Changed
- `_default_template()` prefers Chinese GB templates (previously preferred the English
  template, which produced inches and no frame)
- `add_dimensions(..., relayout=True)`: automatically re-lays out views after annotation

### Known issues
- Interference intersection returned `(None, 1)`, unresolved
- Mates not implemented

## [0.6.0] - 2026-11-02

### Added
- `revolve()` on all three axes (volume error 0.00% on all three)
- Automatic annotation `add_dimensions()` / `count_dimensions()`
- Assembly `AssemblyBuilder` (insert + fix)

### Fixed
- `_view_list()` used `GetViews`, which returns a native PyIDispatch; the exception was
  silently swallowed by `except: continue`, so counting always returned 0 views

### Discovered
- `AddComponent5` requires the part to be **opened first**, otherwise it silently returns None

## [0.5.0] - 2026-11-02

### Added
- Two-level connection fallback (`GetActiveObject` → `CreateInstance`) with actionable errors
- GB material library `gb_materials.py`: 20 grades, auto-deployed into SolidWorks' scan path
- Honesty regression tests (4)

### Fixed
- **Physical material was never assigned to SolidWorks**, so the default density was
  1000 kg/m³ (water) — mass was wrong by 7.85×

## [0.4.1] - 2026-11-02

### Added
- Three-tier resource guard (ok / warn / critical) plus safe sweeping `sweep_documents()`

### Fixed
- `conftest.py` cleaned the project root but missed pytest's temp dir, so the live suite
  locked itself out at the 8th document
- `max_documents=0` was rejected as an invalid parameter

## [0.4.0] - 2026-11-01

### Added
- Document cap and automatic release in batch runs
- Straight-edge selection rule `edges_rule` plus read-only preview `preview_edges`
- PDF content verification (PDFium parse + render)

## [0.3.0] - 2026-11-01

### Added
- Three-axis cylinders, revolve about Y, all-edge fillet and chamfer
- Single-STA serialization (MCP concurrency safety)

### Fixed
- World coordinates no longer mirror Z; `merge` actually takes effect; body count is read
  back from SolidWorks instead of counting successful features

## [0.2.0] - 2026-11-01

### Added
- Colour coverage 57% → **100%** (face-level write + readback)
- View layout solver (measured sizes + long-align / height-align / auto scale)
- MCP server (15 tools)
- 5 integration tests

### Fixed
- `swAllBodies = -1` (was mistakenly 2), so `purge_*` had been iterating 0 bodies

## [0.1.0] - 2026-11-01

First usable version: DSL → C# modeling, coloring, import cleanup, PDF atlas, CLI.
