"""Always test this checkout, independently of globally installed versions."""
from pathlib import Path
import sys
import json
import os
import tempfile
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _documents(sw):
    from swforge.session import _value
    import win32com.client
    result = {}
    for raw in (_value(sw, "GetDocuments") or []):
        doc = raw if hasattr(raw, "GetPathName") else win32com.client.Dispatch(raw)
        path, title = str(_value(doc, "GetPathName")), str(_value(doc, "GetTitle"))
        result[(path.lower(), title)] = (path, title)
    return result


@pytest.fixture(autouse=True)
def _sw_document_budget(request):
    """Limit live-test documents, never close unrelated work documents."""
    if not request.node.get_closest_marker("sw") or os.environ.get("SWFORGE_LIVE") != "1":
        yield
        return
    from swforge import get_session
    sw = get_session().sw()
    before = _documents(sw)
    limit = int(os.environ.get("SWFORGE_MAX_DOCUMENTS", "8"))
    if len(before) >= limit:
        pytest.fail(f"SW 已打开 {len(before)} 个文档，达到测试上限 {limit}；请先处理工作文档")
    yield
    after = _documents(sw)
    # v0.4.1 修复：pytest 的 tmp_path 在 temp/pytest-of-<user>/ 下，
    # 旧写法只认 temp/swforge_it，导致用例产生的文档从不回收，
    # 跑到第 8 个就触发上限、后续用例全部 ERROR。
    roots = [
        Path(tempfile.gettempdir()) / "swforge_it",
        Path(tempfile.gettempdir()),                 # pytest-of-<user>/ 也在其下
    ]
    if os.environ.get("SWFORGE_EVIDENCE"):
        roots.append(Path(os.environ["SWFORGE_EVIDENCE"]))
    closed = []
    for key, (path, title) in after.items():
        if key in before or not path:
            continue
        resolved = Path(path).resolve()
        if any(resolved.is_relative_to(root.resolve()) for root in roots):
            # Only this test's new, generated artifacts may discard changes.
            sw.CloseDoc(path)
            closed.append(path)
    remaining = _documents(sw)
    if os.environ.get("SWFORGE_EVIDENCE"):
        log = Path(os.environ["SWFORGE_EVIDENCE"]).parent / "sw_document_counts.jsonl"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"test":request.node.nodeid,"before":len(before),
                "peak_observed":len(after),"after_cleanup":len(remaining),
                "closed":closed}, ensure_ascii=False) + "\n")
    assert len(remaining) < limit, f"SW 文档数量 {len(remaining)} 达到上限 {limit}，停止后续建模"

@pytest.fixture(autouse=True)
def _strict_sw_marker_guard(request, monkeypatch):
    """CI 守卫：没标 sw marker 的用例不许真的连上 SolidWorks。

    为什么用运行时守卫而不是静态扫描
    --------------------------------
    最初写了个文本扫描脚本，检查测试文件里有没有 `PartBuilder(` / `get_session(`
    然后要求同时出现 `pytest.mark.sw`。结果**误报了 4 个文件** ——
    它们只是用 `PartBuilder(...).cylinder(r=0)` 测**参数校验**，
    在连接 SolidWorks 之前就抛异常了，属于合法的离线用例。

    文本匹配分不清"构造对象测校验"和"真的去连"，所以改成运行时拦：
    只有真的调用 `get_session()` 才拦，且在拦的那一刻检查 marker。

    开关：环境变量 SWFORGE_STRICT_MARKERS=1 时启用（CI 里设）。
    本地不设就没有额外行为，跑实机测试不受影响。
    """
    if os.environ.get("SWFORGE_STRICT_MARKERS") != "1":
        yield
        return
    if request.node.get_closest_marker("sw"):
        yield
        return

    import swforge.session as _sess

    real = _sess.get_session
    nodeid = request.node.nodeid

    def _blocked(*a, **k):
        pytest.fail(
            f"{nodeid} 没有 sw marker，却试图连接 SolidWorks。\n"
            f"要么给它加 @pytest.mark.sw，要么让它不依赖真实连接。",
            pytrace=False)

    monkeypatch.setattr(_sess, "get_session", _blocked)
    # 顶层 re-export 也要一起换，否则 `from swforge import get_session` 绕过去了
    try:
        import swforge
        monkeypatch.setattr(swforge, "get_session", _blocked)
    except Exception:
        pass
    yield
    monkeypatch.setattr(_sess, "get_session", real)
