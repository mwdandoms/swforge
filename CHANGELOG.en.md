[中文](CHANGELOG.md) | **English**

# Changelog

This project adheres to [Semantic Versioning](https://semver.org/).

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
