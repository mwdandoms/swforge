# -*- coding: utf-8 -*-
"""v0.9 新增能力的回归测试。

覆盖：
- 批量出图的文件收集与结果结构（纯逻辑，不需要 SolidWorks）
- API 能力探测的清单完整性与反射结果（需要 Interop DLL，不需要 SW 在运行）
- CLI 子命令注册

设计说明
--------
批量出图和能力探测都是 v0.9 的核心卖点，但它们的价值恰恰在"出错时能说清楚"
—— 所以测试重点放在**失败路径的可见性**，而不是只测 happy path。
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------- 批量出图
def test_collect_models_finds_parts(tmp_path):
    from swforge.batch import collect_models

    (tmp_path / "a.SLDPRT").write_bytes(b"x")
    (tmp_path / "b.sldprt").write_bytes(b"x")     # 小写扩展名也要能找到
    (tmp_path / "c.SLDDRW").write_bytes(b"x")
    (tmp_path / "note.txt").write_text("x")

    got = collect_models(str(tmp_path))
    names = [os.path.basename(p) for p in got]
    assert "a.SLDPRT" in names
    assert "b.sldprt" in names, "大小写不敏感匹配失效"
    assert "c.SLDDRW" not in names
    assert "note.txt" not in names


def test_collect_models_recursive(tmp_path):
    from swforge.batch import collect_models

    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "top.SLDPRT").write_bytes(b"x")
    (sub / "deep.SLDPRT").write_bytes(b"x")

    flat = collect_models(str(tmp_path), recursive=False)
    deep = collect_models(str(tmp_path), recursive=True)

    assert len(flat) == 1
    assert len(deep) == 2, "递归收集没生效"


def test_collect_models_rejects_bad_folder():
    from swforge.batch import collect_models

    with pytest.raises(ValueError):
        collect_models(r"C:\definitely\not\a\real\folder\8347")


def test_collect_models_custom_pattern(tmp_path):
    from swforge.batch import collect_models

    (tmp_path / "a.SLDASM").write_bytes(b"x")
    (tmp_path / "b.SLDPRT").write_bytes(b"x")

    got = collect_models(str(tmp_path), pattern="*.SLDASM")
    assert len(got) == 1
    assert got[0].endswith("a.SLDASM")


def test_batch_result_shape(tmp_path):
    """空文件夹要返回明确的失败原因，而不是静默成功。"""
    from swforge.batch import batch_drawings

    res = batch_drawings(str(tmp_path))
    assert res["ok"] is False
    assert "没找到" in res["error"]
    assert res["total"] == 0
    assert res["succeeded"] == 0


def test_batch_report_written(tmp_path):
    from swforge.batch import batch_drawings, write_report

    res = batch_drawings(str(tmp_path))
    out = tmp_path / "report.json"
    write_report(res, str(out))
    assert out.is_file()
    import json
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total"] == 0


# ---------------------------------------------------------------- 能力探测
def test_probe_api_list_is_well_formed():
    """清单本身不能有拼写/重复问题 —— 探测结果的可信度就建立在清单上。"""
    from swforge.probe import RISKY_APIS

    assert len(RISKY_APIS) >= 20, "清单太短，覆盖不到主要风险 API"

    keys = [k for k, *_ in RISKY_APIS]
    assert len(keys) == len(set(keys)), f"有重复的键：{keys}"

    for key, type_name, method_name, impact in RISKY_APIS:
        assert key == key.lower(), f"{key} 应为小写"
        assert type_name.startswith("I"), f"{type_name} 不像 SolidWorks 接口名"
        assert method_name and method_name[0].isupper(), f"{method_name} 不像方法名"
        assert impact, f"{key} 缺少「缺了会怎样」的说明"


def test_probe_covers_core_paths():
    """主链路依赖的 API 必须在清单里，否则探测给不出完整结论。"""
    from swforge.probe import RISKY_APIS

    keys = {k for k, *_ in RISKY_APIS}
    required = {
        "insert_model_annotations",   # 自动标注
        "body_copy2",                 # 干涉求交
        "body_operations2",
        "add_component5",             # 装配
        "add_mate5",                  # 配合
        "face_get_surface",
        "entity_select4",
        "visible_entities2",          # 总尺寸
        "add_dimension2",
        "create_mass_property",       # 质量属性
    }
    missing = required - keys
    assert not missing, f"清单缺少主链路 API：{missing}"


def _interop_available():
    try:
        from swforge.probe import _find_interop
        dll, _ = _find_interop()
        return bool(dll) and os.path.isfile(dll)
    except Exception:
        return False


needs_interop = pytest.mark.skipif(
    not _interop_available(), reason="本机没有 SolidWorks Interop DLL")


@needs_interop
@pytest.mark.sw
def test_probe_api_returns_verdict():
    """探测必须有明确结论 —— 这是它存在的唯一理由。"""
    from swforge.probe import probe_api

    r = probe_api()
    assert r["ok"], r.get("error")
    assert r["total_count"] >= 20
    assert r["available_count"] >= 1
    assert "apis" in r
    assert r["summary"], "没有生成人读摘要"

    # 每个条目都要有 exists 字段
    for k, v in r["apis"].items():
        assert "exists" in v, f"{k} 缺少 exists"
        assert "impact" in v, f"{k} 缺少 impact"


@needs_interop
@pytest.mark.sw
def test_probe_api_is_fast():
    """探测要够快，否则没人会用它做开工前检查。"""
    from swforge.probe import probe_api

    r = probe_api()
    assert r["elapsed_s"] < 30, f"探测耗时 {r['elapsed_s']} 秒，太慢"


@needs_interop
@pytest.mark.sw
def test_probe_finds_annotations_on_drawingdoc():
    """实测发现 InsertModelAnnotations4 在 IDrawingDoc 上。

    这条用例锁死这个事实 —— 之前清单里写成 IModelDocExtension，
    导致探测误报「缺失」，把一个能用的 API 报成不可用。
    """
    from swforge.probe import probe_api

    r = probe_api()
    a = r["apis"].get("insert_model_annotations") or {}
    assert a.get("exists"), "InsertModelAnnotations4 没探测到"
    # 如果清单里的类型写错了，全局扫描会把真实类型报出来
    if a.get("found_on"):
        assert a["found_on"] == "IDrawingDoc", \
            f"实际位置变了：{a['found_on']}"


# ---------------------------------------------------------------- CLI
def test_cli_has_v09_commands():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    p = subprocess.run([sys.executable, "-X", "utf8", "-m", "swforge.cli", "--help"],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    out = p.stdout
    assert "batch" in out, "CLI 缺少 batch 子命令"
    assert "capabilities" in out, "CLI 缺少 capabilities 子命令"


def test_version_is_v09():
    import swforge
    assert swforge.__version__.startswith("0.9"), swforge.__version__


def test_v09_exports_present():
    import swforge
    for name in ("batch_drawings", "collect_models", "write_report", "probe_api"):
        assert name in swforge.__all__, f"__all__ 缺少 {name}"
        assert hasattr(swforge, name), f"{name} 没导出"
