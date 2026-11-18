"""1.9.3 新增净距与原地改参的离线边界（不连 SW）。

真机行为在 tests/test_v193_live.py（标 sw）。
"""
import pytest

import swforge
from swforge.clearance import check_clearance
from swforge.rebuild import set_parameters


# ────────────────────────── check_clearance 输入校验 ──────────────────────────

def test_clearance_requires_existing_sldasm(tmp_path):
    with pytest.raises(ValueError):
        check_clearance(str(tmp_path / "missing.SLDASM"))


def test_clearance_rejects_non_assembly(tmp_path):
    part = tmp_path / "part.SLDPRT"
    part.write_bytes(b"not an assembly")
    with pytest.raises(ValueError):
        check_clearance(str(part))


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), "2"])
def test_clearance_rejects_bad_minimum(tmp_path, value):
    asm = tmp_path / "asm.SLDASM"
    asm.write_bytes(b"x")
    with pytest.raises(ValueError):
        check_clearance(str(asm), minimum_mm=value)


def test_clearance_rejects_three_components(tmp_path):
    asm = tmp_path / "asm.SLDASM"
    asm.write_bytes(b"x")
    with pytest.raises(ValueError):
        check_clearance(str(asm), components=["a", "b", "c"])


def test_clearance_rejects_bare_string_components(tmp_path):
    asm = tmp_path / "asm.SLDASM"
    asm.write_bytes(b"x")
    with pytest.raises(ValueError):
        check_clearance(str(asm), components="auger-1")


def test_clearance_exported_from_root():
    assert swforge.check_clearance is check_clearance


# ────────────────────────── set_parameters 输入校验 ──────────────────────────

def test_set_parameters_requires_exact_keys(tmp_path):
    part = tmp_path / "part.SLDPRT"
    part.write_bytes(b"x")
    with pytest.raises(ValueError):
        set_parameters(str(part), {"Height": 75.0})


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf"), "75"])
def test_set_parameters_rejects_bad_values(tmp_path, value):
    part = tmp_path / "part.SLDPRT"
    part.write_bytes(b"x")
    with pytest.raises(ValueError):
        set_parameters(str(part), {"D3@helix@part.Part": value})


def test_set_parameters_rejects_empty_parameters(tmp_path):
    part = tmp_path / "part.SLDPRT"
    part.write_bytes(b"x")
    with pytest.raises(ValueError):
        set_parameters(str(part), {})


def test_set_parameters_rejects_non_part(tmp_path):
    asm = tmp_path / "asm.SLDASM"
    asm.write_bytes(b"x")
    with pytest.raises(ValueError):
        set_parameters(str(asm), {"D3@helix@part.Part": 75.0})


def test_set_parameters_rejects_bad_tolerance(tmp_path):
    part = tmp_path / "part.SLDPRT"
    part.write_bytes(b"x")
    with pytest.raises(ValueError):
        set_parameters(str(part), {"D3@helix@part.Part": 75.0}, tolerance_pct=-1)


def test_set_parameters_rejects_bad_expected_volume(tmp_path):
    part = tmp_path / "part.SLDPRT"
    part.write_bytes(b"x")
    with pytest.raises(ValueError):
        set_parameters(str(part), {"D3@helix@part.Part": 75.0}, expect_volume_mm3=0)


def test_set_parameters_exported_from_root():
    assert swforge.set_parameters is set_parameters


# ────────────────────────── CLI 出口 ──────────────────────────

def test_cli_help_lists_new_commands(capsys):
    from swforge.cli import _main

    with pytest.raises(SystemExit):
        _main(["--help"])
    out = capsys.readouterr().out
    for command in ("spring", "auger-flight", "clearance", "set-parameters"):
        assert command in out
    assert "\n    blank " not in out


def test_cli_clearance_reports_bad_path(capsys):
    from swforge.cli import _main

    code = _main(["clearance", r"Z:\nowhere\missing.SLDASM"])
    import json

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert "SLDASM" in payload["error"]


def test_cli_set_parameters_reports_bad_path(capsys, tmp_path):
    """这条守着「CLI 参数与 argparse 定义对不上」这类错（曾经少定义 --material）。"""
    from swforge.cli import _main

    params = tmp_path / "params.json"
    params.write_text('{"D3@helix@part.Part": 75.0}', encoding="utf-8")
    code = _main(["set-parameters", str(tmp_path / "missing.SLDPRT"),
                  "--parameters", str(params)])
    import json

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["ok"] is False
    assert "does not exist" in payload["error"] or "SLDPRT" in payload["error"]
