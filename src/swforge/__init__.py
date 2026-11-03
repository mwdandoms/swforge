# -*- coding: utf-8 -*-
"""swforge —— SolidWorks 自动化工具箱。

把两类能力合到一起：

* **几何**：声明式 DSL → 生成 C# 早期绑定 → 编译执行（批量建模快 3~10 倍）
* **出图**：委托 AssetMate_MechDog 做标注与自检，本地负责排版与成册

快速开始
--------
>>> from swforge import PartBuilder, FaceRule, apply_rules
>>> b = PartBuilder(r"D:\\out\\SWFORGE_支架.SLDPRT")
>>> b.box("底板", 0, 200, 0, 10, 0, 200, "steel")
>>> b.tube_y("立柱", 0, 1000, 0, 0, 150, 150, wall=6.3, color="yellow")
>>> r = b.build()
>>> r.ok, r.bodies
"""

from .session import SWSession, get_session, SWError, BridgeLost
from .modeling import PartBuilder, BuildResult, Material, COLORS, preview_edges
from .resources import (document_inventory, resource_status, sweep_documents,
                        ensure_capacity)
from .spec import builder_from_spec
from .gb_materials import GB_MATERIALS, ensure_library, material_names
from .assembly import AssemblyBuilder, list_components, check_interference
from .interference import body_interference, check_all_pairs
from .mates import MateBuilder, list_mates
from .dims import add_overall_dimensions
from .batch import batch_drawings, collect_models, write_report
from .probe import probe_api
from .colors import FaceRule, apply_rules, read_back
from .cleanup import survey, delete_bodies, purge_giant, purge_small
from .drawing import (have_mechdog, produce, export_pdf, normalize_layout,
                      make_atlas, delivery_check, add_dimensions, count_dimensions)

__version__ = "0.9.0"

__all__ = [
    "__version__",
    # session
    "SWSession", "get_session", "SWError", "BridgeLost",
    # modeling
    "PartBuilder", "BuildResult", "Material", "COLORS", "builder_from_spec", "preview_edges",
    "document_inventory", "resource_status", "sweep_documents", "ensure_capacity",
    "GB_MATERIALS", "material_names", "ensure_library",
    # assembly
    "AssemblyBuilder", "list_components", "check_interference", "body_interference", "check_all_pairs",
    # mates / dims
    "MateBuilder", "list_mates", "add_overall_dimensions",
    # batch
    "batch_drawings", "collect_models", "write_report", "probe_api",
    # colors
    "FaceRule", "apply_rules", "read_back",
    # cleanup
    "survey", "delete_bodies", "purge_giant", "purge_small",
    # drawing
    "have_mechdog", "produce", "export_pdf", "normalize_layout",
    "make_atlas", "delivery_check", "add_dimensions", "count_dimensions",
]

