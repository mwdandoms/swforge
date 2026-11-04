[中文](limitations.md) | **English**

# Known limitations

An honest list. These are things the current version **cannot** do —
not "will be better later" politeness.

---

## Versions

| Item | Status |
|---|---|
| SolidWorks 2025 SP5.0 | ✅ fully verified |
| SolidWorks 2019–2024 | ❌ **untested** |
| Older file formats | ❌ unsupported (files saved by 2025 cannot be opened by 2019) |

The generated C# calls the Interop DLL of whatever version is installed, so it will
**probably** run on 2024 — but untested is not supported. Version compatibility is the
main goal of v0.9.

---

## Geometry

| Item | Note |
|---|---|
| Primitives | box, plate, 4-plate square tube (XYZ), cylinder (XYZ), revolve (XYZ), fillet, chamfer |
| Revolve profile | must be a closed polygon, may not self-intersect |
| Edge rules | straight edges only (filtered by axis + length); no radius-based edge selection |
| Negative-offset planes | fail on some versions; the builder only inserts an offset plane when `y0 > 0` |
| Performance | about **2.65 s per shape**; 100 shapes take roughly 4.5 minutes |

---

## Drawings

| Item | Note |
|---|---|
| Auto annotation | `InsertModelAnnotations4` inserts model driving dimensions, **deduplicated across views**, capped around 18 |
| Overall dimensions | supported, but **the right/top view may snap to inner contours** (measured 114 / 14 where 100 was expected) |
| Dimension avoidance | ❌ none; dimensions may overlap geometry or each other |
| **Tolerances** | v1.4 accepts explicit symmetric/bilateral/limit/fit requirements with readback; no automatic grade selection |
| **Surface finish** | v1.4 supports native straight-edge attachment, leaders and standalone symbols; positions in metres; curved edges and assembly-view attachment are unverified; no automatic avoidance |
| Geometric tolerance (GD&T) | ❌ unsupported |
| Full annotation pipeline | ❌ MechDog's `annotations=True` path still produces PDF `err=1` |

**Conclusion**: explicit tolerances and surface finish can be added in v1.4. Drawings still need process review, complete annotation and human sign-off. See [annotation usage](annotations.md).

---

## Assembly

| Item | Note |
|---|---|
| Insert + fix | ✅ |
| Concentric mate | v1.4.1 supports explicit persistent face references, including unequal hole/shaft radii; automatic selection can still choose unintended faces |
| Coincident mate | v1.4.1 supports explicit planar faces with assembly-space normal and gap readback |
| Distance / angle / gear mates | ❌ not implemented |
| Sub-assemblies | ❌ untested |
| Assembly-level interference API | ❌ **returns 0 for a known 500 mm³ overlap on this machine — unusable** |
| Interference detection | ✅ via part-level boolean intersection (bodies must be in the same part) |
| BOM | ❌ not implemented |
| Exploded views | ❌ not implemented |

---

## Resources and stability

| Item | Note |
|---|---|
| Document cap | 8 by default; creation is refused above it (configurable per call) |
| Resource guard | three tiers (ok / warn / critical) plus safe sweeping |
| Scope of the cap | **guarantees document count only**, not that any given model cannot crash |
| Closing documents | only documents this run created; anything with unsaved changes is skipped |
| Killing processes | ❌ never; the user must handle it |

---

## Platform

* Windows only (depends on COM + Interop DLL)
* Python 3.10+ (verified on 3.14.3)
* Requires a full SolidWorks installation (a Viewer-only install will not work)
