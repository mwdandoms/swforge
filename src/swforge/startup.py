# -*- coding: utf-8 -*-
"""确保 SolidWorks 在运行 —— swforge 原本缺的这一环。

背景
----
`win32com.client.Dispatch("SldWorks.Application")` 走的是 COM 自动激活：
SCM 根据 LocalServer32 注册项去拉起 SLDWORKS.exe。这条路在下面几种情况下会失败：

  · 进程创建被沙箱 / 安全软件挡住  → CO_E_SERVER_EXEC_FAILURE (0x80080005)
  · 启动项权限不足 / 以不同完整性级别运行
  · SW 启动时的许可、引导对话框卡住

原实现没有退路，只能等 60 秒后超时。这里补上：先直接启动 exe，再连 COM。

用法
----
    from swforge.startup import ensure_running
    info = ensure_running()            # 需要时启动，返回诊断信息
    info = ensure_running(visible=False, wait_s=180)

    # 或命令行
    swforge start --wait 180
"""
from __future__ import annotations

import os
import subprocess
import time

from .sw_target import SW_YEARS, active_sw, registered_exe, selected_year


def _common_paths() -> list[str]:
    r"""常见安装位置（按优先级）。按年份生成，不写死 2025。

    1.9.0 之前只有 ``E:\SW2025`` / ``D:\SW2025`` 两条，装 2024 或 2026 的机器
    走不到兜底路径（注册表查询是首选，但注册表被清理时只能靠这里）。
    """
    out: list[str] = []
    for year in SW_YEARS:
        for letter in "EDCF":
            out.append(rf"{letter}:\SW{year}\SOLIDWORKS\SLDWORKS.exe")
    out += [
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe",
        r"D:\SOLIDWORKS\SLDWORKS.exe",
    ]
    return out


# 常见安装位置（按优先级）
COMMON_PATHS = _common_paths()

# 启动后等待窗口/COM 就绪的轮询间隔
POLL_S = 3.0


def find_exe(explicit: str | None = None) -> tuple[str | None, str]:
    """找 SLDWORKS.exe。返回 (路径, 来源说明)。"""
    year = selected_year()
    if year:
        target = registered_exe(year)
        if not target:
            return None, f"SolidWorks {year} COM 版本未注册"
        requested = explicit or os.environ.get("SWFORGE_SW_EXE")
        if requested and os.path.normcase(os.path.abspath(requested)) != os.path.normcase(str(target)):
            return None, f"指定的程序与 SolidWorks {year} 注册路径不一致"
        return str(target), f"SolidWorks {year} 注册表 LocalServer32"

    if explicit:
        p = os.path.expanduser(explicit)
        return (p, "参数指定") if os.path.isfile(p) else (None, f"参数指定的路径不存在：{p}")

    env = os.environ.get("SWFORGE_SW_EXE")
    if env and os.path.isfile(env):
        return env, "环境变量 SWFORGE_SW_EXE"

    try:
        from .resources import paths
        p = getattr(paths, "sldworks_exe", None)
        if p and os.path.isfile(p):
            return p, "resources.paths"
    except Exception:                                          # noqa: BLE001
        pass

    p = registered_exe()
    if p:
        return str(p), "注册表 LocalServer32"

    for p in COMMON_PATHS:
        if os.path.isfile(p):
            return p, "常见安装位置"
    return None, "未找到 SLDWORKS.exe"


def process_running() -> bool:
    """有没有 SLDWORKS.exe 进程 —— 纯进程检查，**不触发 COM 自动启动**。

    这一点很关键：如果用 Dispatch 判断"在不在跑"，Dispatch 本身会把 SW 拉起来，
    就永远走不到「自己启动 exe」这条修复路径上了。
    """
    try:
        # 注意：tasklist 输出是系统 ANSI（简中 = GBK），不能按 UTF-8 解码，
        # 否则 reader 线程抛 UnicodeDecodeError。这里按字节比 ASCII 标记。
        raw = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/NH"],
            capture_output=True, timeout=15,
            creationflags=0x08000000 if os.name == "nt" else 0,
        ).stdout or b""
        return b"SLDWORKS.EXE" in raw.upper()
    except Exception:                                          # noqa: BLE001
        return False


def com_reachable(timeout_s: float = 0) -> bool:
    """COM 能不能调到 RevisionNumber。进程已在跑时用这个确认就绪。"""
    deadline = time.time() + max(0.0, timeout_s)
    while True:
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            year = selected_year()
            sw = active_sw(year) if year else win32com.client.GetActiveObject("SldWorks.Application")
            _ = sw.RevisionNumber
            return True
        except Exception:                                      # noqa: BLE001
            if time.time() >= deadline:
                return False
            time.sleep(POLL_S)
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:                              # noqa: BLE001
                pass


def is_running() -> bool:
    """在跑且 COM 可达。"""
    return process_running() and com_reachable()


def launch(exe: str) -> subprocess.Popen:
    """脱离父进程启动 SW，父进程退出不影响它。"""
    flags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        flags |= subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen([exe], close_fds=True, creationflags=flags)


def _set_visible(sw, visible: bool) -> bool | None:
    try:
        sw.Visible = visible
        return True
    except Exception:                                          # noqa: BLE001
        return None


def ensure_running(exe: str | None = None, wait_s: int = 180,
                   visible: bool = True) -> dict:
    """确保 SW 可用。已连上就直连；连不上就启动 exe 再连。

    返回 {ok, via, exe, launched, waited_s, visible, error, hint}
    """
    info = {"ok": False, "via": None, "exe": None, "launched": False,
            "waited_s": 0.0, "visible": None, "error": None, "hint": None}
    t0 = time.time()
    year = selected_year()
    if year:
        path, source = find_exe(exe)
        info["exe"] = path
        if not path:
            info.update(error=source)
            return info
        if com_reachable():
            info.update(ok=True, via="existing", waited_s=round(time.time()-t0, 1))
            _finish_visible(info, visible)
            return info
        if process_running():
            info.update(error=f"SolidWorks {year} 未就绪，已有 SolidWorks 进程",
                        hint=f"请从 {path} 手动启动或等待 {year} 完成启动，再重试。")
            return info

    # ---- 1) 进程已在跑：只确认 COM 是否就绪（不再触发 COM 自动启动）
    if process_running():
        if com_reachable(timeout_s=min(20, wait_s)):
            info.update(ok=True, via="existing")
            info["waited_s"] = round(time.time() - t0, 1)
            _finish_visible(info, visible)
            return info
        # 进程在但 COM 不通 —— 多半被对话框挡住
        info.update(waited_s=round(time.time() - t0, 1),
                    error="SLDWORKS.exe 在跑，但 COM 调不通",
                    hint=("SW 多半被「许可 / 欢迎 / 恢复文档」等对话框挡住，"
                          "去桌面点掉再重试；或先 Stop-Process 结束它后重跑本命令。"))
        return info

    # ---- 2) 没在跑 → 自己启动 exe（不依赖 COM 自动激活）
    path, src = find_exe(exe)
    info["exe"] = path
    if not path:
        info.update(error="找不到 SLDWORKS.exe",
                    hint=f"{src}。设置环境变量 SWFORGE_SW_EXE 指向 SLDWORKS.exe 后重试。")
        return info

    try:
        launch(path)
        info["launched"] = True
        info["via"] = f"launched ({src})"
    except Exception as exc:                                   # noqa: BLE001
        info.update(error=f"启动失败：{type(exc).__name__}: {exc}",
                    hint=("CO_E_SERVER_EXEC_FAILURE / PermissionError 通常是"
                          "进程创建被沙箱或安全软件挡住："
                          "1) 放宽 DSH 沙箱到 workspace-write 或更高；"
                          "2) 把 SLDWORKS.exe 加入杀软白名单；"
                          "3) 先手动双击启动 SW，再调用本库。"))
        return info

    # ---- 3) 轮询等进程起来 + COM 就绪
    while time.time() - t0 < wait_s:
        time.sleep(POLL_S)
        if process_running() and com_reachable():
            info.update(ok=True)
            info["waited_s"] = round(time.time() - t0, 1)
            _finish_visible(info, visible)
            return info

    info["waited_s"] = round(time.time() - t0, 1)
    info["error"] = f"已启动但 {wait_s} 秒内未就绪"
    info["hint"] = ("SW 可能被「许可 / 欢迎 / 恢复文档」等对话框挡住，"
                    "去桌面上看一眼把它点掉，再重试。")
    return info


def _finish_visible(info: dict, visible: bool):
    """刚启动时 COM 对象可能还没完全就绪，设 Visible 要重试几次。"""
    if not visible:
        return
    last = None
    for _ in range(6):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()          # 主线程也要初始化，否则报"尚未调用 CoInitialize"
            year = selected_year()
            sw = active_sw(year) if year else win32com.client.GetActiveObject("SldWorks.Application")
            sw.Visible = True
            info["visible"] = True
            return
        except Exception as exc:                               # noqa: BLE001
            last = exc
            time.sleep(2)
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
    info["visible"] = False
    info["visible_error"] = f"{type(last).__name__}: {last}"
