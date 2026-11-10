[中文](README.md) | **English**

# swforge

**Less repetitive work in SolidWorks. More reusable engineering results.**

Build parameterized parts, apply materials and colors, prepare assemblies and drawings, and deliver BOMs and PDFs through repeatable workflows—with readback checks where supported.

[![PyPI](https://img.shields.io/pypi/v/swforge)](https://pypi.org/project/swforge/) [![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## What you can do

| Work | Community features |
|---|---|
| Repeated part designs | Plates, tubes, cylinders, revolved bodies, cuts, holes, fillets, chamfers and copy-only variants |
| Materials and appearance | GB-designated materials, rule-based colors and readback |
| Assemblies | Components, mates, interference checks, variants and native BOM tables |
| Drawings | Standard views, sections, details, explicit dimensions, tolerances and surface-finish symbols |
| Consistent presentation | A0–A4 GB-oriented templates, first-angle projection, title fields and basic font/line-weight checks |
| Deliverables | Batch drawings, multi-sheet books, PDF/DWG/DXF export and artifact freshness records |
| AI-assisted work | MCP access, alongside Python and command-line interfaces |

Checks expose their coverage and limitations. Generated drawings still require engineering review.

## How it compares

| Approach | Published focus | Where swforge fits |
|---|---|---|
| Project-specific macros | Replaying a particular sequence; capabilities depend on implementation | Reusable workflows spanning modeling, variants, drawings and delivery |
| [CAD+ Toolset](https://cadplus.xarial.com/) | Properties, batch processing, export, BOM and desktop/PDM utilities | Parameterized engineering tasks accessible through scripts, CLI and AI assistants |
| [AssetMate MechDog](https://github.com/wudahua/Solidworks_AssetMate_MechDog) | SolidWorks MCP, drawing annotations, feature ledgers and delivery checks | Parameterized geometry/mechanical families, variants, basic GB-oriented drawings and multi-sheet delivery; optional drawing enhancements can work with MechDog |

This is a positioning comparison based on official descriptions, not a shared-task benchmark or a claim that competing products lack particular features. Only SW2025 SP5 has been tested locally; no speed multiplier or cross-version guarantee is claimed.

## Install

Windows, Python 3.10+ and your own licensed SolidWorks installation are required.

```bash
pip install swforge
pip install "swforge[mcp,pdf]"
swforge --help
```

Keep source models and use new output paths. The default open-document limit is eight.

## Open-source boundary

The GitHub repository and PyPI Community distributions are MIT-licensed, including commercial use. They include modeling, materials/colors, assemblies, annotations, BOMs, drawing books, batch APIs, basic GB templates/checks, readback and document protection.

Advanced GB clause review, raster/drawing-set review and process-rule orchestration implementations are withheld from this release, including the sdist and wheel. They remain local pending a separate module and licensing decision. They are not advertised as an available paid product. Earlier MIT releases retain their original license.

Basic GB coverage is finite: limited fit codes/size ranges, no certified exact long-FangSong font coverage, and no complete GB/manufacturing/strength certification. Five GD&T characteristics have interfaces; saved-and-reopened flatness was the native fixture tested this round. See [scope](COMMUNITY_SCOPE.json) and [validation](docs/validation-community.md).

MCP migration: use `sw_discover`, `sw_describe`, `sw_invoke` and `sw_status`; original operation names are invoked through the gateway. Community Python and CLI operations remain available. See [migration](docs/community-migration.md).

## Acknowledgements

Original and dependency license notices are preserved. Thanks to [AssetMate MechDog](https://github.com/wudahua/Solidworks_AssetMate_MechDog) and other open-source projects. Report issues with your SW version and a minimal example; omit confidential models.
