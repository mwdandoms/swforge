"""swforge —— SolidWorks 自动化工具箱。

把两类能力合到一起：

* **几何**：声明式 DSL → 生成 C# 早期绑定 → 编译执行并回读
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
from .resources import document_inventory, resource_status, sweep_documents, ensure_capacity
from .spec import builder_from_spec
from .gb_materials import GB_MATERIALS, ensure_library, material_names
from .status import check_status
from .views_extra import add_section_view, add_detail_view
from .assembly import AssemblyBuilder, list_components, check_interference, read_volume
from .interference import body_interference, check_all_pairs
from .mates import MateBuilder, list_mates
from .dims import add_overall_dimensions
from .bom import collect_bom, insert_bom_table, bom_to_csv, bom_to_markdown
from .guard import document_guard, activate_verified, verify_active
from .batch import batch_drawings, collect_models, write_report
from .probe import probe_api
from .colors import FaceRule, apply_rules, read_back
from .cleanup import survey, delete_bodies, purge_giant, purge_small
from .drawing import have_mechdog, produce, export_pdf, normalize_layout, make_atlas, delivery_check, add_dimensions, count_dimensions
from .annotations import add_surface_finish, add_surface_finishes, list_surface_edges, list_dimensions, set_tolerance
from .mate_faces import list_mate_faces, apply_face_mates, inspect_face_mates
from .variants import list_model_parameters, create_variant
from .drawing_review import audit_drawing, suggest_drawing_layout, record_drawing_revision
from .circle_dimensions import list_drawing_circles, add_diameter_dimension
from .mechanical import frame_plan, spur_gear_plan, create_weldment_frame, create_spur_gear, inspect_mechanical, create_mechanical_variant, mechanical_drawing
from .version import __version__
from .gb_styles import validate_gb_template, apply_gb_styles, read_gb_styles, gb_template_path
from .gb_standards import fit_deviation, ra_series_valid, general_tolerance_note
from .hole_families import hole_plate_plan, create_hole_plate, inspect_hole_plate
from .hole_annotations import hole_plate_drawing
from .gdandt import add_geometric_tolerance
from .assembly_workflows import inspect_assembly, assembly_bom, plan_assembly_variant, create_assembly_variant
from .assembly_bom_table import insert_assembly_bom
from .drawing_books import create_drawing_book, drawing_book_snapshot, review_drawing_book, layout_drawing_book, stamp_drawing_book
from .gb_check import GBSpec, check_gb_drawing, evaluate_gb_completeness, collect_drawing_snapshot
from .gb_notes import build_tech_requirements, format_title_block_fields, add_tech_requirements, fill_title_block
from .position_dimensions import list_position_targets, add_position_dimension
__all__ = ['validate_gb_template', 'apply_gb_styles', 'read_gb_styles', 'gb_template_path', 'fit_deviation', 'ra_series_valid', 'general_tolerance_note', 'create_standard_member', 'member_plan', 'MaterialLibrary', 'default_library', 'hole_plate_plan', 'create_hole_plate', 'inspect_hole_plate', 'hole_plate_drawing', 'add_geometric_tolerance', 'inspect_assembly', 'assembly_bom', 'plan_assembly_variant', 'create_assembly_variant', 'insert_assembly_bom', 'create_drawing_book', 'drawing_book_snapshot', 'review_drawing_book', 'layout_drawing_book', 'stamp_drawing_book', 'GBSpec', 'check_gb_drawing', 'evaluate_gb_completeness', 'collect_drawing_snapshot', 'build_tech_requirements', 'format_title_block_fields', 'add_tech_requirements', 'fill_title_block', 'list_position_targets', 'add_position_dimension', 'frame_plan', 'spur_gear_plan', 'create_weldment_frame', 'create_spur_gear', 'inspect_mechanical', 'create_mechanical_variant', 'mechanical_drawing', 'ensure_running', 'find_sw_exe', 'list_model_parameters', 'create_variant', 'audit_drawing', 'suggest_drawing_layout', 'record_drawing_revision', 'list_drawing_circles', 'add_diameter_dimension', 'list_mate_faces', 'apply_face_mates', 'inspect_face_mates', 'add_surface_finish', 'add_surface_finishes', 'list_surface_edges', 'list_dimensions', 'set_tolerance', 'check_status', 'read_volume', 'add_section_view', 'add_detail_view', 'collect_bom', 'insert_bom_table', 'bom_to_csv', 'bom_to_markdown', 'document_guard', 'activate_verified', 'verify_active', '__version__', 'SWSession', 'get_session', 'SWError', 'BridgeLost', 'PartBuilder', 'BuildResult', 'Material', 'COLORS', 'builder_from_spec', 'preview_edges', 'document_inventory', 'resource_status', 'sweep_documents', 'ensure_capacity', 'GB_MATERIALS', 'material_names', 'ensure_library', 'AssemblyBuilder', 'list_components', 'check_interference', 'body_interference', 'check_all_pairs', 'MateBuilder', 'list_mates', 'add_overall_dimensions', 'batch_drawings', 'collect_models', 'write_report', 'probe_api', 'FaceRule', 'apply_rules', 'read_back', 'survey', 'delete_bodies', 'purge_giant', 'purge_small', 'have_mechdog', 'produce', 'export_pdf', 'normalize_layout', 'make_atlas', 'delivery_check', 'add_dimensions', 'count_dimensions']
from .startup import ensure_running, find_exe as find_sw_exe
from .library import MaterialLibrary, default_library
from .mechanical import create_standard_member, member_plan

from .spring import SpringSpec, create_spring, validate as spring_validate
from .auger import create_auger_flight
from .clearance import check_clearance
from .rebuild import set_parameters
from .design import resolve_design, create_design_variant
from .feature_tree import inspect_feature_tree
__all__ += ['SpringSpec', 'create_spring', 'spring_validate', 'create_auger_flight',
            'check_clearance', 'set_parameters', 'resolve_design',
            'create_design_variant', 'inspect_feature_tree']
