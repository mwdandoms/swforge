[中文](https://github.com/mwdandoms/swforge/blob/main/README.md) | **English**

# swforge

**Drive your local SolidWorks from Python, CLI, or MCP — modeling, GB material assignment, assembly mates, interference checks, and GB-standard drawings, with every step verified by reading the result back.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![SolidWorks](https://img.shields.io/badge/SolidWorks-2025%20SP5%20tested-red)]()
[![PyPI](https://img.shields.io/pypi/v/swforge)](https://pypi.org/project/swforge/)
[![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/mwdandoms/swforge/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-mwdandoms.github.io-blue)](https://mwdandoms.github.io/swforge/)

[![swforge demo: driving SolidWorks from code](https://raw.githubusercontent.com/mwdandoms/swforge/main/demo/poster.png)](https://github.com/mwdandoms/swforge/releases/download/v1.4.1/swforge-demo-2m21s-1080p60.mp4)

> ▶ **Click the image to watch the 2 min 21 s demo** (6.7 MB) — starting from a
> closed SolidWorks: modeling → GB materials → GB drawing → dimensions →
> surface finish → tolerances → PDF → assembly → mates → interference,
> **with no manual operation at any point**.

---

## Why use it

| Other tools | swforge |
|---|---|
| A call that returns without error is treated as success | Reads the real result back and stops on mismatch |
| Default density is water, mass off by 7.85× | Built-in GB material library, density re-derived and checked |
| Drawing frame and title block don't match local practice | GB frame, title block, surface finish, dimensional tolerances |
| Interference reported as yes / no | Exact volume, e.g. 4000.0 mm³ |

---

## What it does

**Modeling** — boxes, plates, rectangular tubes (all three axes), cylinders, revolves, fillets, chamfers

**Machining features** — rectangular cut on a named body, through / blind / counterbored holes on any axis and direction, hole grids

**Assembly** — component placement, coincident / concentric / distance / angle / lock mates, explicit persistent-face mates, interference checking

**Drawings** — GB three views, section and detail views, automatic dimensions, diameter dimensions, surface finish symbols, dimensional tolerances, export to PDF / DWG / DXF

**Drawing review** — views outside the sheet, view overlap, dangling annotations, missing properties, model-to-drawing consistency

**Also** — BOM tables, batch drawing generation, document-count guard

---

## Install

```bash
pip install swforge              # library only
pip install "swforge[mcp,pdf]"   # with the MCP server and PDF preview
```

Requires Windows, a full SolidWorks installation, and Python 3.10+.
**Start SolidWorks yourself first, then call the library.**

Verified on SolidWorks 2025 SP5.0 / Windows 11 / Python 3.14. Other SW versions are untested.

---

## Thirty-second example

```python
from swforge import PartBuilder

b = PartBuilder(r"F:\out\plate.SLDPRT", material="Q235")
b.box("plate", 0, 100, 0, 20, 0, 60)
b.hole("mount", "plate", axis="y", x=30, y=20, z=30,
       diameter=10, through_all=True, direction=-1,
       counterbore_diameter=16, counterbore_depth=4)

r = b.build(keep_open=False)
assert r.ok, r.error
print(r.mass_kg, r.volume_mm3)   # real values read back from SolidWorks
```

---

## Check your environment first

```bash
swforge selftest
```

Runs live on your own machine and prints pass/fail for each check.

---

## Not implemented

- **Geometric tolerancing (GD&T)**
- **Complete hole callouts** (position, depth, hole tables) — only diameter dimensions on circular edges for now
- **Weldments / cut lists**, **involute gears**
- Text overlap in drawing review is an **approximation**
- Live-verified only on SolidWorks 2025 SP5.0

See [limitations](https://github.com/mwdandoms/swforge/blob/main/docs/limitations.en.md) and the [issue log](https://github.com/mwdandoms/swforge/blob/main/docs/issue-log.md), which includes the unfixed ones.

---

## Docs

[Quickstart](https://github.com/mwdandoms/swforge/blob/main/docs/quickstart.md) ·
[Feature matrix](https://github.com/mwdandoms/swforge/blob/main/docs/features.md) ·
[Docs site](https://mwdandoms.github.io/swforge/)

---

## License

MIT.
