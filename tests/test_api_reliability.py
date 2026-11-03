"""无需运行 SW 的输入、会话隔离和 MCP 调度回归测试。"""

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swforge import cli
from swforge.session import STAWorker, SWError, SWSession, get_session
from swforge.spec import builder_from_spec


def _box():
    return {"tag": "底板", "x0": 0, "x1": 40, "y0": 0, "y1": 10, "z0": 0, "z1": 30}


def test_spec_supports_new_geometry(tmp_path):
    spec = {"boxes": [_box()],
            "cylinders": [{"tag": "轴", "axis": "x", "x": 100, "r": 8, "h": 40}],
            "revolves": [{"tag": "轮", "profile_pts": [[0, 0], [12, 0], [12, 8], [0, 8]]}],
            "fillets": [{"tag": "底板", "r": 1}], "chamfers": [{"tag": "轴", "d": 1}]}
    builder = builder_from_spec(str(tmp_path / "part.SLDPRT"), spec)
    assert builder.shape_count == 3
    assert builder.feature_count == 5
    assert not (tmp_path / "part.SLDPRT").exists()


@pytest.mark.parametrize("spec", [
    [], {}, {"boxs": [_box()]}, {"boxes": {}}, {"boxes": [None]},
    {"boxes": [_box()], "merge": "false"},
    {"boxes": [{**_box(), "x1": float("nan")}]},
    {"tubes": [{"tag": "管", "axis": "unknown"}]},
    {"tubes": [{"tag": "管", "axis": "x", "x0": 0, "x1": 100,
                "cy": 0, "cz": 0, "sy": 20, "sz": 20, "wall": 10}]},
    {"boxes": [{**_box(), "unused": 1}]},
    {"cylinders": [{"tag": "轴", "axis": "q"}]},
])
def test_invalid_spec_fails_without_creating_file(tmp_path, spec):
    path = tmp_path / "part.SLDPRT"
    with pytest.raises(ValueError):
        builder_from_spec(str(path), spec)
    assert not path.exists()


def test_cli_validate_only_does_not_build(tmp_path, monkeypatch, capsys):
    from swforge.modeling import PartBuilder
    def unexpected_build(*args, **kwargs):
        raise AssertionError("validation must never execute build")
    monkeypatch.setattr(PartBuilder, "build", unexpected_build)
    spec_path = tmp_path / "part.json"
    spec_path.write_text(json.dumps({"boxes": [_box()]}), encoding="utf-8")
    assert cli.main(["build", str(spec_path), "--out", str(tmp_path / "part.SLDPRT"),
                     "--validate-only"]) == 0
    assert json.loads(capsys.readouterr().out)["validated"] is True


def test_cli_reports_failure_exit_status(monkeypatch, capsys):
    import swforge.cleanup as cleanup
    monkeypatch.setattr(cleanup, "survey", lambda: {"ok": False, "error": "没有打开的文档"})
    assert cli.main(["survey"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_cli_reports_invalid_spec_as_json(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"boxes": [{"x0": 0}]}', encoding="utf-8")
    assert cli.main(["build", str(path), "--out", str(tmp_path / "part.SLDPRT")]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False and "boxes[0]" in result["error"]


def test_sessions_are_thread_local():
    main = get_session()
    sessions = []
    thread = threading.Thread(target=lambda: sessions.extend([get_session(), get_session()]))
    thread.start()
    thread.join()
    assert sessions[0] is sessions[1]
    assert sessions[0] is not main


def test_explicit_session_rejects_cross_thread_use():
    session = SWSession()
    session._check_thread()
    errors = []
    def check():
        try:
            session._check_thread()
        except SWError as exc:
            errors.append(str(exc))
    thread = threading.Thread(target=check)
    thread.start()
    thread.join()
    assert len(errors) == 1


def test_close_all_preserves_unsaved_documents():
    closed = []
    def doc(path, dirty, title):
        return SimpleNamespace(GetPathName=path, GetSaveFlag=dirty, GetTitle=title)
    sw = SimpleNamespace(GetDocuments=[doc("C:/clean.SLDPRT", False, "clean.SLDPRT"),
                                      doc("C:/dirty.SLDPRT", True, "dirty.SLDPRT"),
                                      doc("", False, "新建零件")], CloseDoc=closed.append)
    session = SWSession()
    session.sw = lambda: sw
    assert session.close_all() == 1
    assert closed == ["clean.SLDPRT"]
    closed.clear()
    assert session.close_all(discard_unsaved=True) == 3
    assert len(closed) == 3


def test_sta_worker_serializes_operations_and_balances_com(monkeypatch):
    events = []
    fake_com = SimpleNamespace(COINIT_APARTMENTTHREADED=2,
        CoInitializeEx=lambda flag: events.append(("init", threading.get_ident())),
        CoUninitialize=lambda: events.append(("uninit", threading.get_ident())),
        PumpWaitingMessages=lambda: None)
    monkeypatch.setitem(sys.modules, "pythoncom", fake_com)
    worker = STAWorker()
    main_id = threading.get_ident()
    calls = []
    def job(index):
        calls.append((index, threading.get_ident()))
        return index * 2
    futures = [worker.submit(job, index) for index in range(8)]
    assert [future.result(timeout=5) for future in futures] == list(range(0, 16, 2))
    worker.close()
    assert [item[0] for item in calls] == list(range(8))
    assert len({item[1] for item in calls}) == 1
    assert calls[0][1] != main_id
    assert events == [("init", calls[0][1]), ("uninit", calls[0][1])]
    with pytest.raises(SWError):
        worker.submit(job, 9)


def test_sta_worker_keeps_running_after_operation_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "pythoncom", SimpleNamespace(COINIT_APARTMENTTHREADED=2,
        CoInitializeEx=lambda _: None, CoUninitialize=lambda: None, PumpWaitingMessages=lambda: None))
    worker = STAWorker()
    def fail():
        raise ValueError("bad input")
    with pytest.raises(ValueError, match="bad input"):
        worker.submit(fail).result(timeout=5)
    assert worker.submit(lambda: 7).result(timeout=5) == 7
    worker.close()


def test_mcp_validation_does_not_connect_solidworks(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from swforge.server import mcp
    from swforge.modeling import PartBuilder
    monkeypatch.setattr(PartBuilder, "build", lambda **kwargs: pytest.fail("must not build"))
    # Direct pure-tool call avoids creating a Windows event loop in restricted CI.
    tool = mcp._tool_manager.get_tool("sw_validate_part")
    result = tool.fn(out_path=str(tmp_path / "part.SLDPRT"), spec={"boxes": [_box()]})
    assert result["ok"] and result["validated"]
