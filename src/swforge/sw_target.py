"""Resolve the SolidWorks automation target without changing COM registration."""
from __future__ import annotations

import os
from pathlib import Path

SW_YEARS = tuple(range(2026, 2018, -1))
_PROGID = "SldWorks.Application"
_INTEROP = "SolidWorks.Interop.sldworks.dll"


def selected_year() -> int | None:
    raw = os.environ.get("SWFORGE_SW_YEAR", "").strip()
    if not raw:
        return None
    if raw not in {str(year) for year in SW_YEARS}:
        raise ValueError("SWFORGE_SW_YEAR must be a year from 2019 to 2026")
    return int(raw)


def progid(year: int | None) -> str:
    return f"{_PROGID}.{year - 1992}" if year else _PROGID


def registered_exe(year: int | None = None) -> Path | None:
    """Read the merged COM registration used by the current Windows user."""
    if os.name != "nt":
        return None
    import winreg

    def default_value(key):
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key) as handle:
            return winreg.QueryValueEx(handle, "")[0]

    try:
        clsid = default_value(progid(year) + r"\CLSID")
        value = default_value(rf"CLSID\{clsid}\LocalServer32")
    except OSError:
        return None
    text = os.path.expandvars(value.strip())
    end = text.lower().find(".exe")
    if end < 0:
        return None
    path = Path(text[:end + 4].lstrip('"'))
    return path if path.is_file() else None


def effective_year() -> int | None:
    year = selected_year()
    if year:
        return year
    exe = registered_exe()
    if exe:
        return next((candidate for candidate in SW_YEARS if registered_exe(candidate) == exe), None)
    return None


def install_candidates() -> list[str]:
    year = selected_year()
    exe = registered_exe(year)
    if year:
        # The registered version-specific executable is also the launch target.
        return [str(exe.parent)] if exe else []

    dirs = [os.environ.get("SW_INSTALL_DIR"), os.environ.get("SOLIDWORKS_DIR")]
    if exe:
        dirs.append(str(exe.parent))
    if os.name == "nt":
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for candidate in SW_YEARS:
                key = rf"SOFTWARE\SolidWorks\SOLIDWORKS {candidate}\Setup"
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        dirs.append(winreg.QueryValueEx(handle, "SolidWorks Folder")[0])
                except OSError:
                    continue
    for drive in "EDCFG":
        dirs.extend(rf"{drive}:\SW{year}\SOLIDWORKS" for year in SW_YEARS)
        dirs.append(rf"{drive}:\Program Files\SOLIDWORKS Corp\SOLIDWORKS")
    return list(dict.fromkeys(d for d in dirs if d))


def install_dir() -> str | None:
    return next((d for d in install_candidates() if (Path(d) / _INTEROP).is_file()), None)


def template_dirs(year: int) -> list[Path]:
    base = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    path = base / "SOLIDWORKS" / f"SOLIDWORKS {year}" / "templates"
    override = os.environ.get("SW_TEMPLATE_DIR")
    return [Path(override), path] if override else [path]


def verify_revision(sw, year: int | None):
    revision = sw.RevisionNumber
    revision = revision() if callable(revision) else revision
    if year and int(str(revision).split(".", 1)[0]) != year - 1992:
        raise RuntimeError(f"Requested SolidWorks {year}, received revision {revision}")
    return sw


def dynamic_sw(obj):
    """把 COM 对象统一包成【动态绑定】代理。

    为什么必须这样做（2025 SP5 实测，5 个实机用例全红）：
    `win32com.client.Dispatch()` / `GetActiveObject()` 在 `gen_py` 里已有该类型库
    缓存时会返回**早绑定**代理；早绑定把 `OpenDoc6` 的 byref 参数按 `int` 解释，
    传 `VARIANT(VT_BYREF|VT_I4)` 直接
    `TypeError: int() argument must be a string, a bytes-like object or a real number, not 'VARIANT'`。
    并装 2019/2025 时这个缓存命中与否还取决于哪一版先被访问过 —— 结果就是
    "同一套用例在 2019 全绿、在 2025 全红"。动态绑定没有这个类型假设。
    """
    from win32com.client import dynamic

    raw = getattr(obj, "_oleobj_", obj)
    try:
        return dynamic.Dispatch(raw)
    except Exception:                                    # noqa: BLE001
        return obj


def active_sw(year: int):
    import win32com.client

    try:
        return verify_revision(
            dynamic_sw(win32com.client.GetActiveObject(progid(year))), year)
    except Exception as exc:
        raise RuntimeError(
            f"SolidWorks {year} is not reachable. Start that version and wait for COM readiness."
        ) from exc


def native_source(source: str) -> str:
    """Use the same COM target in generated C# and check it before document access."""
    return source + _NATIVE_CONNECTION


_NATIVE_CONNECTION = r"""
internal static class SwforgeConnection {
    static readonly int target = TargetMajor();

    static int TargetMajor() {
        string value = System.Environment.GetEnvironmentVariable("SWFORGE_SW_YEAR");
        if (System.String.IsNullOrWhiteSpace(value)) return 0;
        int year;
        if (!System.Int32.TryParse(value, out year) || year < 2019 || year > 2026)
            throw new System.InvalidOperationException("Invalid SWFORGE_SW_YEAR");
        return year - 1992;
    }

    static string ProgId {
        get { return target == 0 ? "SldWorks.Application" : "SldWorks.Application." + target; }
    }

    static SolidWorks.Interop.sldworks.ISldWorks Validate(object app) {
        var sw = (SolidWorks.Interop.sldworks.ISldWorks)app;
        int actual = System.Int32.Parse(sw.RevisionNumber().Split('.')[0]);
        int interop = typeof(SolidWorks.Interop.sldworks.ISldWorks).Assembly.GetName().Version.Major;
        if (actual != interop || (target != 0 && target != actual))
            throw new System.InvalidOperationException(
                "SolidWorks version mismatch: runtime=" + actual + ", interop=" + interop + ", target=" + target);
        return sw;
    }

    internal static SolidWorks.Interop.sldworks.ISldWorks Active() {
        return Validate(System.Runtime.InteropServices.Marshal.GetActiveObject(ProgId));
    }

    internal static SolidWorks.Interop.sldworks.ISldWorks Connect() {
        if (target != 0) return Active();
        return Validate(System.Activator.CreateInstance(System.Type.GetTypeFromProgID(ProgId)));
    }
}
"""
