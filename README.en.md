[中文](README.md) | **English**

# dsh-sw-toolkit

**Drive your local SolidWorks from Python, CLI, or MCP — modeling, GB material assignment, assembly mates, interference checks, and GB-standard drawings, with readback verification at every step.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![SolidWorks](https://img.shields.io/badge/SolidWorks-2025%20SP5%20tested-red)]()
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-124%20passed-brightgreen)]()

> Tested end-to-end only on **SolidWorks 2025 SP5.0 + Windows + Python 3.14**.
> Version compatibility (targeting 2019+) is the main goal of the next release.

---

## What problem does it solve

SolidWorks automation falls into three camps, each with its own traps:

| Approach | Batch modeling | Drawings | Coloring | Assembly mates |
|---|---|---|---|---|
| VBA / raw COM | Slow (IDispatch round-trips) | Everyone rolls their own | Body-level assignment silently fails | Possible, very verbose |
| Commercial add-ins | Fast | Strong | Strong | Strong |
| **This project** | Generates C# early-binding code — fast | **GB frame + auto dimensions + overall dimensions** | **Face-level write + readback, 100%** | **Concentric / coincident with auto face selection** |

Concrete problems it addresses:

1. **LLMs produce invalid parameters** → `spec.py` validates before execution and reports `cylinders[0]: cylinder.axis must be x/y/z` instead of crashing inside COM.
2. **You cannot tell whether a build succeeded** → body count, envelope, per-face colors, material, mass, and volume are all read back.
3. **Coloring appears to be set but is not applied** → face-level write plus readback comparison, verified 126/126 faces.
4. **GB material assignment fails silently** → the default density falls back to **1000 kg/m³ (water)**, making mass wrong by 7.85×. The project ships a 20-grade GB material library and deploys it automatically.
5. **Drawings come out in inches with no frame** → automatically picks the Chinese `gb_<paper>.drwdot` template, which carries the frame, title block, material, weight, and scale.
6. **No overall dimensions** → `dims.py` adds overall length/height explicitly from the view's extreme visible vertices.
7. **Interference checks return nothing** → the assembly-level API returns 0 for a known 500 mm³ overlap on this machine, so the project uses **part-level boolean intersection** and reports an exact 500.000 mm³.
8. **Documents pile up and drag SolidWorks down** → a three-tier resource guard plus safe sweeping.

---

## Key numbers

| Item | Value |
|---|---|
| Source | **~4,400 lines** of Python across 14 modules |
| Tests | **124** (95 offline + 29 live) |
| MCP tools | **22** |
| Public exports | **41** |
| GB material grades | **20** (density / elastic modulus / Poisson's ratio / standard reference) |
| Geometry | box / plate / tube(XYZ) / cylinder(XYZ) / revolve(XYZ) / fillet / chamfer |
| Verified environment | SolidWorks 2025 SP5.0 (33.5.0) + Python 3.14.3 |

---

## Install

```powershell
git clone https://github.com/<you>/dsh-sw-toolkit.git
cd dsh-sw-toolkit
python -m pip install -e ".[mcp,pdf]"
```

**Requirements**: Windows + SolidWorks (verified on 2025 SP5.0) + Python 3.10+

Optional extras:

| extras | Provides |
|---|---|
| `[mcp]` | MCP server (22 tools) |
| `[pdf]` | PDFium-based PDF content verification |
| `[mechdog]` | Delegates deep annotation and manufacturing review to MechDog |

---

## Quick start

### One-command self check

```powershell
dsh-sw capabilities
```

Prints the SolidWorks version, connection latency, and whether MechDog is available.

### Modeling with a GB material

```python
from dsh_sw_toolkit import PartBuilder

b = PartBuilder(r"D:\out\bracket.SLDPRT", material="Q235")
b.box("base plate", 0, 160, 0, 20, 0, 100, "steel")
b.tube_y("column", 20, 140, 60, 0, 40, 40, wall=6, color="yellow")
b.cylinder("hole", axis="y", x=80, y=20, z=50, r=8, h=20, color="gray")

r = b.build()
print(r.ok, r.bodies, r.mass_kg, r.volume_mm3)
# True 10 3.281 417920.0
```

### Drawings (GB frame + auto dimensions + overall dimensions)

```python
from dsh_sw_toolkit import produce, add_dimensions, normalize_layout, export_pdf

produce(model, drawing, paper="A3")          # picks gb_a3.drwdot automatically
add_dimensions(drawing, overall=True)        # model dimensions + overall length/height
normalize_layout(drawing)                    # long-align / height-align / 35 mm+ spacing
export_pdf(drawing, r"D:\out\drawing.pdf")
```

The result contains a GB frame (zones A–F / 1–8), a title block (material / weight / scale),
millimetre dimensions, overall dimensions, and three views aligned per drafting convention.

### Assembly, mates, interference

```python
from dsh_sw_toolkit import AssemblyBuilder, MateBuilder, body_interference

a = AssemblyBuilder(r"D:\out\assembly.SLDASM")
a.add(r"D:\out\base.SLDPRT", 0, 0, 0, fixed=True)   # coordinates are in mm
a.add(r"D:\out\pin.SLDPRT",  60, 0, 0)
a.build()

m = MateBuilder(r"D:\out\assembly.SLDASM")
m.concentric(0, 1)        # finds equal-radius cylindrical faces automatically
res = m.apply()
# the pin moves from 60 mm to 0 mm and becomes coaxial

body_interference(part, "A", "B")
# {'interfere': True, 'interference_volume_mm3': 500.0}
```

### MCP

```json
{
  "mcpServers": {
    "dsh-sw": { "command": "solidworks-dsh-sw.exe" }
  }
}
```

22 tools: `sw_build_part`, `sw_apply_colors`, `sw_produce_drawing`, `sw_layout_views`,
`sw_export_pdf`, `sw_overall_dimensions`, `sw_body_interference`, `sw_resource_status`, and more.

---

## Design principles

1. **Never fake success** — `ready_for_manufacture` is always `False`, `review_required` is always `True`, and tests enforce it.
2. **Destructive operations default to dry-run** — `purge_*` and `sweep_documents` list before acting.
3. **Never touch the user's documents** — only documents this run created are closed; anything with unsaved changes is skipped.
4. **Never invent engineering data** — drawings do not get automatic tolerances; materials use a GB table with cited standards.
5. **Judgments must rest on independent readback** — `errStatus` and `ok` can both be false signals (see pitfalls).

---

## Pitfalls we hit (the most valuable asset here)

| Symptom | Truth |
|---|---|
| `AddMate5` returns `errStatus=1` | That is not a failure — `swAddMateError_NoError = 1` |
| `Operations2` returns `(None, 1)` | Document bodies are not API temporary bodies; call `Copy2()` first |
| `FixComponent()` returns None | It actually succeeded; check `IsFixed` instead |
| `material="Q235"` is accepted | It was never applied — mass was computed at water density (1000 kg/m³) |
| `IFace2.GetSurface()` reports "member not found" | Unavailable via pywin32 late binding; must go through C# early binding |
| Cannot connect when SolidWorks was started via COM | It is not in the ROT; fall back from `GetActiveObject` to `CreateInstance` |
| Assembly parts land 60 metres away | `AddComponent5` expects **metres** while the project convention is **millimetres** |

See `docs/pitfalls.md` for the full list.

---

## Known limitations

* Verified only on SolidWorks 2025 SP5.0 — **2019–2024 untested**
* Generated `.SLDPRT` files use the current format; older SolidWorks cannot open them (no version-downgrade save yet)
* Automatic annotation inserts model driving dimensions, deduplicated across views, capped around 18; overall dimensions are added separately by `dims.py`
* Overall dimensions on the right/top views may snap to inner contours (to be fixed)
* Tolerances and surface finish are **not generated** (deliberate: no invented engineering requirements)
* The assembly-level interference API is unusable on this machine; interference goes through part-level booleans
* Modeling costs about **2.65 s per shape**; 100 shapes take roughly 4.5 minutes

See `docs/limitations.md` for details.

---

## Repository layout

```
src/dsh_sw_toolkit/
├── session.py       unified session: liveness probe, classified retry, single-STA serialization
├── modeling.py      DSL → C# early-binding modeling + face-level coloring
├── colors.py        rule-based face coloring + readback
├── cleanup.py       STEP import survey and junk-body purge
├── gb_materials.py  20 GB grades + material library generation
├── assembly.py      component insertion + fixing
├── mates.py         concentric / coincident mates (auto face selection)
├── interference.py  exact interference volume
├── dims.py          explicit overall length / height dimensions
├── drawing.py       drawing production, template selection, annotation, layout, PDF
├── resources.py     three-tier resource guard
├── spec.py          JSON specification validation
├── server.py        MCP server (22 tools)
└── cli.py           command line
```

---

## Development

```powershell
# offline tests only (no SolidWorks required; use this in CI)
python -m pytest tests -q -m "not sw"

# full suite (SolidWorks must be running)
$env:DSH_SW_LIVE = "1"
python -m pytest tests -q
```

**SolidWorks must be started manually and its main window fully visible**, otherwise the live tests fail.

---

## Roadmap

| Version | Theme | Status |
|---|---|---|
| v0.5 | Connection fallback, GB materials, honesty tests | ✅ |
| v0.6 | Three-axis revolve, auto dimensions, assembly | ✅ |
| v0.7 | GB frame, millimetre units | ✅ |
| v0.8 | Overall dimensions, mates, exact interference | ✅ |
| **v0.9** | **SolidWorks version compatibility (2019+)** | planned |
| v1.0 | Tolerances/finish, BOM, exploded views | planned |

---

## License

MIT. See [LICENSE](LICENSE).

The optional [MechDog](https://github.com/wudahua/Solidworks_AssetMate_MechDog) dependency
(also MIT) is called only through its Python API; no code is copied.
