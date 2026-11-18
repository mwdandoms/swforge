"""Offline search over the registered operation catalogue."""
import re
import unicodedata

_ALIASES = {
    "sw_check_clearance": ("查干涉", "干涉检查", "过盈", "装配净距", "间隙", "interference", "clearance"),
    "sw_produce_drawing": ("生成工程图", "出工程图", "出图", "三视图", "drawing generation"),
    "sw_export_pdf": ("导出PDF", "输出PDF", "打印图纸", "pdf export"),
    "sw_create_spring": ("弹簧", "压缩弹簧", "spring"),
    "sw_create_auger_flight": ("绞龙", "螺旋叶片", "auger"),
    "sw_compute_blank": ("绞龙下料", "下料", "扇形展开", "flight blank"),
    "sw_build_part": ("建模", "建零件", "零件建模", "part modeling"),
    "sw_model_parameters": ("查看尺寸", "读取尺寸", "模型参数", "model dimensions"),
    "sw_create_variant": ("另存改参", "另存变型", "零件变型", "part variant"),
    "sw_inspect_feature_tree": ("特征树", "设计树", "feature tree"),
    "sw_add_axis_centerline": ("轴中心线", "添加中心线", "axis centerline"),
    "sw_style_drawing_annotations": ("整理标注", "标注样式", "annotation style"),
    "sw_inspect_drawing_annotations": ("标注冲突", "标注检查", "标注交叉", "annotation collision"),
    "sw_add_surface_finish": ("粗糙度", "表面粗糙度", "surface finish"),
    "sw_check_gdt": ("形位公差", "几何公差", "gdt"),
    "sw_assembly_bom": ("明细表", "物料清单", "bom"),
    "sw_apply_face_mates": ("装配配合", "配合", "mates"),
    "sw_check_gb_drawing": ("国标检查", "国标审图", "gb drawing"),
    "sw_list_materials": ("材质列表", "材料牌号", "material grades"),
    "sw_resource_status": ("窗口数量", "文档数量", "内存", "resource status"),
}
_STOP_WORDS = {"a", "the", "and", "for", "solidworks", "swforge", "sw", "open",
               "check", "inspect", "fix", "make", "create", "show", "file", "please"}
_GENERIC_CJK = {"打开", "检查", "查看", "修复", "创建", "生成", "操作", "读取", "帮我"}


def normalize(value):
    text = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def _contains(text, term):
    if re.search(r"[\u3400-\u9fff]", term):
        return term in text
    return bool(re.search(r"(?<![a-z0-9])"+re.escape(term)+r"(?![a-z0-9])", text))


def rank_operations(query, rows, limit):
    query = normalize(query)
    if not query:
        return []
    terms = {word for word in re.findall(r"[a-z0-9]+",query) if word not in _STOP_WORDS}
    ranked = []
    for row in rows:
        name = normalize(row["name"])
        short = name[3:] if name.startswith("sw ") else name
        description = normalize(row["description"])
        aliases = tuple(map(normalize,_ALIASES.get(row["name"],())))
        if query in (name,short):
            score = 1000
        elif query in aliases:
            score = 120
        else:
            score = 45 if any(_contains(query,a) for a in aliases) else 0
            if query not in _GENERIC_CJK and (terms or re.search(r"[\u3400-\u9fff]",query)):
                score += 30 if _contains(name,query) else 15 if _contains(description,query) else 0
            score += sum(7 if _contains(name,w) else 2 if _contains(description,w) else 0 for w in terms)
        if score:
            ranked.append(dict(row,score=score,description=row["description"].splitlines()[0][:180] if row["description"] else ""))
    return sorted(ranked,key=lambda row:(-row["score"],not row["enabled"],row["name"]))[:limit]
