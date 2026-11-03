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
