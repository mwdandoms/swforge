"""Explicit effects for the MCP operations exposed by this distribution."""
from pathlib import Path

_GROUPS = {
    ("system", "read"): """
        sw_ping sw_capabilities sw_resources sw_resource_status
    """,
    ("review", "read"): """
        sw_check_gb_drawing sw_list_position_targets sw_inspect_hole_plate sw_check_gdt
        sw_inspect_assembly sw_plan_assembly_variant sw_drawing_book_snapshot sw_review_drawing_book
        sw_inspect_mechanical sw_model_parameters sw_drawing_circles sw_audit_drawing
        sw_inspect_drawing_annotations sw_suggest_drawing_layout sw_list_surface_edges sw_list_dimensions
        sw_list_mate_faces sw_inspect_face_mates sw_validate_part sw_list_colors sw_read_colors sw_survey
        sw_list_materials sw_preview_edges sw_validate_template sw_read_gb_styles sw_check_drawing_completeness
        sw_inspect_feature_tree sw_resolve_design sw_check_clearance sw_compute_blank sw_delivery_check
    """,
    ("model", "write"): """
        sw_create_weldment_frame sw_create_spring sw_create_auger_flight sw_create_hole_plate
        sw_create_spur_gear sw_mechanical_variant sw_create_variant sw_build_part sw_apply_colors
        sw_ensure_material_library sw_create_design_variant
    """,
    ("drawing", "write"): """
        sw_add_tech_requirements sw_fill_title_block sw_add_curated_dimensions sw_add_position_dimension
        sw_hole_plate_drawing sw_add_gdt sw_insert_assembly_bom sw_stamp_drawing_book sw_create_drawing_book
        sw_layout_drawing_book sw_mechanical_drawing sw_add_diameter_dimension sw_style_drawing_annotations
        sw_add_axis_centerline sw_add_surface_finish sw_add_surface_finishes sw_set_tolerance sw_produce_drawing
        sw_layout_views sw_apply_gb_styles
    """,
    ("assembly", "write"): "sw_create_assembly_variant sw_apply_face_mates",
    ("delivery", "read"): "sw_assembly_bom",
    ("delivery", "write"): "sw_export_pdf sw_make_atlas",
    ("admin", "destructive"): "sw_close_all sw_purge_giant sw_purge_small sw_sweep_documents",
}
EFFECT_TABLE = {name: key for key,names in _GROUPS.items() for name in names.split()}
# These are outputs only for the named operations. For annotations, drawing_path is the input.
_EXTRA_OUTPUTS = {
    "sw_create_weldment_frame": ("drawing_path",),
    "sw_create_spur_gear": ("drawing_path",),
    "sw_mechanical_variant": ("drawing_path",),
    "sw_create_variant": ("drawing_path", "summary_csv"),
}
_DRY_RUN = {"sw_layout_views", "sw_apply_colors"}


def classify(name):
    return EFFECT_TABLE.get(name, ("unknown", "unknown"))


def output_paths(name, args):
    if name == "sw_produce_drawing":
        return [args.get("out_path") or str(Path(args["model_path"]).with_suffix(".SLDDRW"))]
    if name == "sw_export_pdf":
        return [args.get("pdf_path") or str(Path(args["drawing_path"]).with_suffix(".pdf"))]
    return [args[key] for key in ("out_path", "out_pdf", "pdf_path")+_EXTRA_OUTPUTS.get(name,())
            if isinstance(args.get(key),str) and args[key]]


def effective_risk(name, risk, args):
    if name in _DRY_RUN and args.get("dry_run") is True:
        return "read"
    if risk == "write" and any(Path(p).exists() or Path(p).is_symlink() for p in output_paths(name,args)):
        return "destructive"
    return risk
