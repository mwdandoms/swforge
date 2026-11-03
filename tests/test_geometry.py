"""v0.3 无 SW 回归：拒绝无效输入、失败不可被旧文件掩盖。"""
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dsh_sw_toolkit.modeling import PartBuilder


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True])
def test_rejects_nonfinite_geometry(tmp_path, value):
    b = PartBuilder(tmp_path / "part.SLDPRT")
    with pytest.raises(ValueError):
        b.box("bad", 0, value, 0, 1, 0, 1)
    assert b.shape_count == 0


@pytest.mark.parametrize("kwargs", [dict(r=0), dict(h=-1), dict(axis="q"),
                                       dict(color="missing"), dict(color=[1.2,0,0])])
def test_rejects_invalid_cylinder_without_mutation(tmp_path, kwargs):
    b = PartBuilder(tmp_path / "part.SLDPRT")
    with pytest.raises(ValueError):
        b.cylinder("bad", **kwargs)
    assert b.shape_count == 0


@pytest.mark.parametrize("profile", [[(0,0),(0,1),(0,2)],
                                    [(-1,0),(1,0),(1,2)],
                                    [(0,0),(2,3),(0,3),(3,0)],
                                    [(0,0),(2,0),(2,0),(0,2)]])
def test_rejects_invalid_revolve_profile(tmp_path, profile):
    b = PartBuilder(tmp_path / "part.SLDPRT")
    with pytest.raises(ValueError):
        b.revolve("bad", profile)
    assert b.shape_count == 0


def test_duplicate_tag_and_missing_finish_fail_early(tmp_path):
    b = PartBuilder(tmp_path / "part.SLDPRT").cylinder("shaft")
    with pytest.raises(ValueError, match="唯一"):
        b.box("shaft", 0,1,0,1,0,1)
    with pytest.raises(ValueError, match="找不到"):
        b.fillet("unknown", 2)
    assert b.feature_count == 1


def test_tube_wall_validation_is_atomic(tmp_path):
    b = PartBuilder(tmp_path / "part.SLDPRT")
    with pytest.raises(ValueError):
        b.tube_y("tube", 0,100,0,0,20,30,wall=10)
    assert b.box_count == b.shape_count == 0


def _mock_build(monkeypatch, tmp_path, *, log="", returncode=0, timeout=False):
    import dsh_sw_toolkit.modeling as module
    monkeypatch.setattr(module, "_find_sw_dir", lambda: str(tmp_path))
    def run(args, **kwargs):
        work = os.path.dirname(args[-1])
        if log:
            with open(os.path.join(work,"result.log"),"w",encoding="utf-8") as fh:
                fh.write(log)
        if timeout:
            raise subprocess.TimeoutExpired(args, 1)
        return SimpleNamespace(returncode=returncode,stdout="",stderr="")
    monkeypatch.setattr(module.subprocess,"run",run)


def test_old_model_and_log_cannot_turn_compile_failure_into_success(monkeypatch, tmp_path):
    path = tmp_path / "old.SLDPRT"
    path.write_bytes(b"previous valid model")
    b = PartBuilder(path).box("box",0,10,0,10,0,10)
    old_log = "DSHSW_RESULT ok=1 failed=0 bodies=1 saved=True errors=0\n"
    with open(b.log_path,"w",encoding="utf-8") as fh:
        fh.write(old_log)
    _mock_build(monkeypatch,tmp_path,returncode=1)
    r = b.build()
    assert not r.ok
    assert r.bodies == 0
    assert path.read_bytes() == b"previous valid model"


@pytest.mark.parametrize("machine_log", [
    "DSHSW_RESULT ok=1 failed=0 bodies=1 saved=False errors=0",
    "DSHSW_RESULT ok=1 failed=0 bodies=1 saved=True errors=32",
    "DSHSW_RESULT ok=1 failed=1 bodies=1 saved=True errors=0",
    "DSHSW_RESULT ok=0 failed=0 bodies=1 saved=True errors=0",
])
def test_build_requires_all_features_and_confirmed_save(monkeypatch,tmp_path,machine_log):
    path = tmp_path / "old.SLDPRT"
    path.write_bytes(b"old")
    b = PartBuilder(path).box("box",0,10,0,10,0,10)
    _mock_build(monkeypatch,tmp_path,log=machine_log)
    assert not b.build().ok


def test_result_uses_true_body_count_and_verified_color_count(monkeypatch,tmp_path):
    path=tmp_path / "merged.SLDPRT"
    path.write_bytes(b"saved")
    b=PartBuilder(path,merge=True).box("a",0,10,0,10,0,10).box("b",5,15,0,10,0,10)
    _mock_build(monkeypatch,tmp_path,log="DSHSW_COLOR total=8 requested=8 verified=7\n"
                "DSHSW_RESULT ok=2 failed=0 bodies=1 saved=True errors=0")
    r=b.build()
    assert r.ok
    assert r.bodies == 1 and r.features_ok == 2
    assert r.color_faces == 7 and r.color_coverage == 0.875 and r.paint_error


def test_timeout_returns_failure_with_preserved_existing_model(monkeypatch,tmp_path):
    path=tmp_path / "old.SLDPRT"
    path.write_bytes(b"old")
    b=PartBuilder(path).cylinder("shaft")
    _mock_build(monkeypatch,tmp_path,timeout=True)
    r=b.build(timeout_s=1)
    assert not r.ok and "超过" in r.error
    assert path.read_bytes() == b"old"
