"""Offline regressions for exact-document targeting and verified results."""
import os
from types import SimpleNamespace

import pytest

from dsh_sw_toolkit import cleanup, colors, drawing


@pytest.mark.parametrize("module", [colors, drawing])
def test_com_object_property_is_not_invoked_as_default_member(module):
    class Proxy:
        _oleobj_ = object()
        def __call__(self):
            raise AssertionError("COM object is callable but is already the return value")
    proxy = Proxy()
    assert module._value(SimpleNamespace(ReturnedObject=proxy), "ReturnedObject") is proxy


class Body:
    def __init__(self, name="body", size=0.1, selected=True, faces=()):
        self.Name, self.size, self.selected, self.faces = name, size, selected, faces

    def GetBodyBox(self):
        return (0, 0, 0, self.size, self.size, self.size)

    def GetFaces(self):
        return self.faces

    def Select(self, append, data):
        return self.selected


class Part:
    def __init__(self, path, bodies=()):
        self.path, self.bodies = os.path.abspath(path), list(bodies)
        self.delete_calls = 0
        self.FeatureManager = self

    def GetPathName(self):
        return self.path

    def GetType(self):
        return 1

    def GetBodies2(self, kind, visible):
        return [] if kind == cleanup.SW_SHEET else self.bodies

    def ClearSelection2(self, all):
        pass

    def InsertDeleteBody2(self, keep):
        self.delete_calls += 1
        return SimpleNamespace(Name="DeleteBody")

    def EditRebuild3(self):
        return True


def bind(monkeypatch, module, sw):
    monkeypatch.setattr(module, "get_session", lambda: SimpleNamespace(sw=lambda: sw))


def test_python_purge_default_is_preview():
    md = Part("preview.SLDPRT", [Body(size=8)])
    result = cleanup.purge_giant(md)
    assert result["dry_run"] and len(result["candidates"]) == 1
    assert md.delete_calls == 0


def test_delete_never_applies_partial_selection():
    bodies = [Body(), Body(selected=False)]
    md = Part("partial.SLDPRT", bodies)
    result = cleanup.delete_bodies(md, bodies)
    assert not result["ok"] and result["deleted"] == 0
    assert md.delete_calls == 0


def test_delete_feature_without_count_change_is_failure():
    md = Part("unchanged.SLDPRT", [Body()])
    result = cleanup.delete_bodies(md, md.bodies)
    assert not result["ok"] and result["deleted"] == 0


def test_empty_survey_has_no_fabricated_envelope(monkeypatch):
    bind(monkeypatch, cleanup, SimpleNamespace(ActiveDoc=Part("empty.SLDPRT")))
    result = cleanup.survey()
    assert result["envelope_mm"] is None
    assert result["total_bodies"] == 0


def test_body_enumeration_errors_are_not_empty_models():
    class Broken:
        def GetBodies2(self, *args):
            raise RuntimeError("bridge lost")
    with pytest.raises(RuntimeError, match="bridge lost"):
        cleanup.purge_giant(Broken())


class Face:
    Normal = (0, 1, 0)
    GetBox = (0, 0, 0, 0.1, 0.1, 0.1)

    def __init__(self, silent=False):
        self.rgb = None
        self.silent = silent

    def SetMaterialPropertyValues2(self, values, *args):
        if not self.silent:
            self.rgb = values.value

    def GetMaterialPropertyValues2(self, *args):
        return self.rgb


def test_color_request_uses_requested_full_path(monkeypatch, tmp_path):
    a, b = Part(tmp_path / "a" / "same.SLDPRT"), Part(tmp_path / "b" / "same.SLDPRT")
    face = Face()
    b.bodies = [Body(faces=[face])]
    requested = []
    sw = SimpleNamespace(ActiveDoc=a)
    sw.OpenDoc = lambda path, kind: requested.append(path) or b
    bind(monkeypatch, colors, sw)
    monkeypatch.setattr(colors, "_save", lambda md: (True, 0, 0))
    result = colors.apply_rules(b.path, [colors.FaceRule("all", (0.2, 0.3, 0.4))])
    assert requested == [os.path.normcase(b.path)]
    assert result["ok"] and result["verified"] == 1


def test_silent_color_write_fails_verification(monkeypatch, tmp_path):
    md = Part(tmp_path / "silent.SLDPRT", [Body(faces=[Face(silent=True)])])
    bind(monkeypatch, colors, SimpleNamespace(ActiveDoc=md))
    monkeypatch.setattr(colors, "_save", lambda md: (True, 0, 0))
    result = colors.apply_rules(md.path, [colors.FaceRule("all", (1, 0, 0))])
    assert not result["ok"] and result["written"] == 1
    assert result["verified"] == 0 and result["failed"] == 1


def test_default_color_is_applied_and_verified(monkeypatch, tmp_path):
    md = Part(tmp_path / "default.SLDPRT", [Body(faces=[Face()])])
    bind(monkeypatch, colors, SimpleNamespace(ActiveDoc=md))
    monkeypatch.setattr(colors, "_save", lambda md: (True, 0, 0))
    result = colors.apply_rules(md.path, [], default_color=(0, 1, 0))
    assert result["ok"] and result["verified"] == 1


@pytest.mark.parametrize("cond", [{"y_max_lt": 10}, {"normal_y_gt": 2}, {"size_gt": float("nan")}])
def test_bad_rule_is_rejected_before_com(cond):
    with pytest.raises(ValueError):
        colors.FaceRule("bad", (1, 0, 0), **cond)


def test_readback_honors_path_and_zero_sample(monkeypatch, tmp_path):
    md = Part(tmp_path / "requested.SLDPRT", [Body(faces=[Face()])])
    sw = SimpleNamespace(ActiveDoc=Part(tmp_path / "other.SLDPRT"), OpenDoc=lambda *a: md)
    bind(monkeypatch, colors, sw)
    assert colors.read_back(md.path, sample=0) == []


class View:
    def __init__(self, name, width=0.1, height=0.08, scale=1):
        self.name, self.width, self.height = name, width, height
        self.ScaleDecimal, self.Position, self.next = scale, (0.1, 0.1), None

    def GetOrientationName(self):
        return "*" + self.name

    def GetNextView(self):
        return self.next

    def GetOutline(self):
        x, y = self.Position
        return (x - self.width * self.ScaleDecimal / 2,
                y - self.height * self.ScaleDecimal / 2,
                x + self.width * self.ScaleDecimal / 2,
                y + self.height * self.ScaleDecimal / 2)


class Drawing:
    def __init__(self, views, path):
        self.views, self.path, self.saved = views, os.path.abspath(path), False
        self.sheetview = View("sheet")
        linked = [self.sheetview, *views]
        for a, b in zip(linked, linked[1:]):
            a.next = b

    def GetType(self):
        return 3

    def GetPathName(self):
        return self.path

    def GetCurrentSheet(self):
        return SimpleNamespace(GetProperties=(0, 0, 0, 0, 0, 0.420, 0.297))

    def GetFirstView(self):
        return self.sheetview

    def GetSheetNames(self):
        return ['Sheet1']

    def EditRebuild3(self):
        return True


def drawing_session(monkeypatch, md):
    from dsh_sw_toolkit import session
    monkeypatch.setattr(session, "get_session", lambda: SimpleNamespace(sw=lambda: SimpleNamespace(ActiveDoc=md)))
    monkeypatch.setattr(drawing, "_vt_pt", lambda x, y: (x, y))
    monkeypatch.setattr(colors, "_save", lambda md: (True, 0, 0))


def test_layout_dry_run_preserves_positions_and_scales(monkeypatch, tmp_path):
    views = [View("Front", 0.4, 0.3), View("Right", 0.2, 0.3), View("Top", 0.4, 0.2)]
    md = Drawing(views, tmp_path / "layout.SLDDRW")
    drawing_session(monkeypatch, md)
    before = [(v.Position, v.ScaleDecimal) for v in views]
    result = drawing.normalize_layout(dry_run=True)
    assert result["ok"] and result["scale"] < 1
    assert result["roles"] == ["main", "top", "right"]
    assert before == [(v.Position, v.ScaleDecimal) for v in views]


def test_layout_keeps_full_gap_after_scaling(monkeypatch, tmp_path):
    main, top, right = View("Front", 0.4, 0.3), View("Top", 0.4, 0.2), View("Right", 0.2, 0.3)
    md = Drawing([main, top, right], tmp_path / "layout.SLDDRW")
    drawing_session(monkeypatch, md)
    result = drawing.normalize_layout()
    assert result["ok"], result
    assert right.GetOutline()[0] - main.GetOutline()[2] >= .035 - 1e-6
    assert main.GetOutline()[1] - top.GetOutline()[3] >= .035 - 1e-6
    assert main.Position[0] == top.Position[0]
    assert main.Position[1] == right.Position[1]


def test_layout_uses_current_sheet_linked_views(monkeypatch, tmp_path):
    md = Drawing([View("Front")], tmp_path / "sheet.SLDDRW")
    md.GetViews = property(lambda: (_ for _ in ()).throw(AssertionError("must not enumerate all sheets")))
    drawing_session(monkeypatch, md)
    assert drawing.normalize_layout(dry_run=True)["views"] == 1


def test_layout_remeasures_fixed_outline_padding_after_scale(monkeypatch, tmp_path):
    class PaddedView(View):
        def GetOutline(self):
            x, y = self.Position
            width = self.width * self.ScaleDecimal + .0119
            height = self.height * self.ScaleDecimal + .0119
            return (x - width / 2, y - height / 2, x + width / 2, y + height / 2)

    main = PaddedView("Front", .4, .3)
    top = PaddedView("Top", .4, .2)
    right = PaddedView("Right", .2, .3)
    md = Drawing([main, top, right], tmp_path / "padded.SLDDRW")
    drawing_session(monkeypatch, md)
    result = drawing.normalize_layout()
    assert result["ok"], result
    assert right.GetOutline()[0] - main.GetOutline()[2] >= .035 - 1e-6
    assert main.GetOutline()[1] - top.GetOutline()[3] >= .035 - 1e-6


def test_failed_export_does_not_pass_using_old_output(monkeypatch, tmp_path):
    md = Drawing([], tmp_path / "source.SLDDRW")
    md.ClearSelection2 = lambda *a: None
    drawing_session(monkeypatch, md)
    monkeypatch.setattr(drawing, "_save_as", lambda *a: (False, 1, 0))
    output = tmp_path / "old.pdf"
    output.write_bytes(b"%PDF-old output")
    result = drawing.export_pdf(md.path, str(output))
    assert not result["ok"]
    assert output.read_bytes() == b"%PDF-old output"


def test_export_activates_requested_drawing(monkeypatch, tmp_path):
    from dsh_sw_toolkit import session
    a, b = Drawing([], tmp_path / "a.SLDDRW"), Drawing([], tmp_path / "b.SLDDRW")
    b.ClearSelection2 = lambda *a: None
    sw = SimpleNamespace(ActiveDoc=a, OpenDoc=lambda *args: b)
    sw.ActivateDoc = lambda path: setattr(sw, "ActiveDoc", b)
    monkeypatch.setattr(session, "get_session", lambda: SimpleNamespace(sw=lambda: sw))
    used = []

    def save(md, path):
        used.append(md)
        with open(path, "wb") as fh:
            fh.write(b"%PDF-new")
        return True, 0, 0

    monkeypatch.setattr(drawing, "_save_as", save)
    monkeypatch.setattr(drawing,"_validate_pdf",lambda *args:{"ok":True,"page_count":1})
    result = drawing.export_pdf(b.path, str(tmp_path / "new.pdf"))
    assert result["ok"] and used == [b]


def test_export_passes_null_dispatch_instead_of_empty_variant():
    import pythoncom
    def save_as(path, version, options, data, err, warn):
        assert data is not None
        assert data.varianttype == pythoncom.VT_DISPATCH
        return True
    md = SimpleNamespace(Extension=SimpleNamespace(SaveAs=save_as))
    assert drawing._save_as(md, "test.SLDDRW") == (True, 0, 0)
