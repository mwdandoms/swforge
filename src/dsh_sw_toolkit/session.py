# -*- coding: utf-8 -*-
"""统一 SolidWorks 会话层。

设计取舍
--------
本项目把「连接」拆成两条路：

1. **早期绑定快路径**（`fast()`）：把 C# 源码编译成内存程序集，
   直接调用 `SolidWorks.Interop.sldworks` 的强类型接口。
   批量几何操作比后期绑定快 3~10 倍，且编译期就能发现签名错误。

2. **后期绑定稳路径**（`sw()`）：`win32com.client.Dispatch`。
   不依赖 Interop DLL，SW 2018~2025 通用，作为兜底和
   pywin32 专属能力（如事件）的入口。

借鉴 AssetMate_MechDog 的 **存活探针 + 忙时重试 + 断线重连**：
SW 的 COM 桥接在长时间空闲后会返回 `Not connected`，而进程本身正常。
缓存一个死 dispatcher 会让后续所有调用失败，所以每次取连接前用
`RevisionNumber`（约 18 ms）探活，失败即丢缓存重新连接。
"""

from __future__ import annotations

import os
import time
import threading
import subprocess
import queue
from concurrent.futures import Future

__all__ = ["SWSession", "get_session", "BridgeLost", "SWError", "STAWorker"]

# SolidWorks COM 相关 HRESULT
_RPC_E_CALL_REJECTED = -2147418111   # 忙
_BUSY_HINTS = ("Call was rejected by callee", "被调用方拒绝")
_LOST_HINTS = (
    "Not connected",
    "未连接",
    "CO_E_OBJNOTCONNECTED",
    "The remote procedure call failed",
    "RPC server is unavailable",
)

LIVENESS_INTERVAL_S = 2.0
RETRY_BACKOFF_S = (0.25, 0.6)


class SWError(RuntimeError):
    """SolidWorks 调用失败。"""


class BridgeLost(SWError):
    """COM 桥接失效，调用方应丢弃缓存后重试。"""


def _is_busy(exc: BaseException) -> bool:
    msg = str(exc)
    return getattr(exc, "hresult", None) == _RPC_E_CALL_REJECTED or any(h in msg for h in _BUSY_HINTS)


def _is_lost(exc: BaseException) -> bool:
    msg = str(exc)
    return any(h in msg for h in _LOST_HINTS)


class SWSession:
    """一个线程内的 SolidWorks 连接；COM 代理禁止跨线程使用。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sw = None                    # 后期绑定对象
        self._sw_type = None               # 早期绑定类型（Type）
        self._last_probe = 0.0
        self.reconnects = 0
        self.stale_drops = 0
        self.busy_retries = 0
        self._owner = None

    def _check_thread(self):
        ident = threading.get_ident()
        if self._owner is None:
            self._owner = ident
        elif self._owner != ident:
            raise SWError("SolidWorks COM 会话不能跨线程使用，请在当前线程调用 get_session()")

    # ------------------------------------------------------------------ 后期绑定
    def sw(self, force: bool = False):
        """返回 `ISldWorks` 后期绑定对象，必要时探活/重连。"""
        import win32com.client  # 延迟导入，便于无 SW 环境跑单测

        with self._lock:
            self._check_thread()
            now = time.time()
            need_probe = force or (now - self._last_probe) >= LIVENESS_INTERVAL_S
            if self._sw is not None and need_probe:
                try:
                    _ = self._sw.RevisionNumber          # 约 18 ms
                    self._last_probe = now
                except Exception as exc:                 # noqa: BLE001
                    if _is_busy(exc):
                        raise  # 忙不表示断线，不能在建模中途创建新连接
                    self._sw = None
                    self.stale_drops += 1
                    # 断线：立刻重连（不重试旧句柄）
            if self._sw is None:
                self._sw = win32com.client.Dispatch("SldWorks.Application")
                self._last_probe = time.time()
                if self.stale_drops:
                    self.reconnects += 1
            return self._sw

    # ------------------------------------------------------------------ 早期绑定
    def fast(self):
        """返回早期绑定 `ISldWorks`（.NET 类型实例）。

        需要 .NET Framework（Windows 自带）与 Interop DLL。
        找不到 DLL 时抛 `SWError`，调用方回退到 `sw()`。
        """
        with self._lock:
            self._check_thread()
            if self._sw_type is None:
                self._sw_type = _load_interop_type()
            if self._sw_type is None:
                raise SWError("找不到 SolidWorks Interop DLL，请改用后期绑定接口")
            return _dispatch_typed(self._sw_type)

    # ------------------------------------------------------------------ 通用调用
    def call(self, fn, *args, **kwargs):
        """带忙重试的调用包装。

        只重试「忙」（RPC_E_CALL_REJECTED），断线不重试而是抛
        `BridgeLost`，让调用方决定是否重跑整个工具——重跑一个
        已经部分执行的建模流程是危险的。
        """
        self._check_thread()
        last = None
        for attempt in range(len(RETRY_BACKOFF_S) + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:                     # noqa: BLE001
                last = exc
                if _is_lost(exc):
                    self._sw = None
                    raise BridgeLost(str(exc)) from exc
                if _is_busy(exc) and attempt < len(RETRY_BACKOFF_S):
                    self.busy_retries += 1
                    time.sleep(RETRY_BACKOFF_S[attempt])
                    continue
                raise
        raise BridgeLost(str(last)) if last else SWError("unknown COM failure")

    # ------------------------------------------------------------------ 探针
    def ping(self) -> dict:
        t0 = time.time()
        sw = self.sw(force=True)
        rev = str(_value(sw, "RevisionNumber"))
        return {
            "ok": True,
            "sw_version": rev,
            "roundtrip_ms": round((time.time() - t0) * 1000, 1),
            "reconnects": self.reconnects,
            "stale_drops": self.stale_drops,
            "busy_retries": self.busy_retries,
        }

    # ------------------------------------------------------------------ 文档
    @property
    def active_doc(self):
        return self.sw().ActiveDoc

    def close_all(self, discard_unsaved: bool = False) -> int:
        """关闭已保存且未修改的文档；明确 discard_unsaved=True 才放弃更改。"""
        sw = self.sw()
        closed = 0
        try:
            docs = _value(sw, "GetDocuments") or []
        except Exception:                                # noqa: BLE001
            docs = []
        for d in docs:
            try:
                if not hasattr(d, "GetPathName"):
                    import win32com.client
                    d = win32com.client.Dispatch(d)
                path = _value(d, "GetPathName")
                if not discard_unsaved:
                    # 读不到保存状态时同样保留文档，避免 CloseDoc 静默丢失更改。
                    if not path or bool(_value(d, "GetSaveFlag")):
                        continue
                title = _value(d, "GetTitle")
                sw.CloseDoc(title or path)
                closed += 1
            except Exception:                            # noqa: BLE001
                pass
        return closed


# ---------------------------------------------------------------------- 单例
_SESSION_LOCAL = threading.local()


def get_session() -> SWSession:
    if not hasattr(_SESSION_LOCAL, "session"):
        _SESSION_LOCAL.session = SWSession()
    return _SESSION_LOCAL.session


def _value(obj, name):
    value = getattr(obj, name)
    return value() if callable(value) and not hasattr(value, "_oleobj_") else value


class STAWorker:
    """MCP 所有 SW 操作串行放在同一个初始化了 COM 的 STA 线程。"""

    def __init__(self):
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread = None
        self._closed = False

    def submit(self, fn, *args, **kwargs) -> Future:
        future = Future()
        with self._lock:
            if self._closed:
                raise SWError("SolidWorks worker 已关闭")
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="dsh-sw-sta", daemon=True)
                self._thread.start()
            self._queue.put((future, fn, args, kwargs))
        return future

    def _run(self):
        com = None
        init_error = None
        try:
            import pythoncom
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            com = pythoncom
        except Exception as exc:
            init_error = exc
        try:
            while True:
                task = self._queue.get()
                if task is None:
                    break
                future, fn, args, kwargs = task
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    if init_error is not None:
                        raise SWError(f"STA COM 初始化失败: {init_error}") from init_error
                    future.set_result(fn(*args, **kwargs))
                except BaseException as exc:
                    future.set_exception(exc)
                finally:
                    if com is not None:
                        com.PumpWaitingMessages()
        finally:
            # 先释放当前线程缓存的 dispatcher，再撤销 COM apartment。
            if hasattr(_SESSION_LOCAL, "session"):
                del _SESSION_LOCAL.session
            if com is not None:
                com.CoUninitialize()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._thread is not None:
                self._queue.put(None)
        if self._thread is not None and self._thread.ident != threading.get_ident():
            self._thread.join(timeout=5)


# ---------------------------------------------------------------------- 早期绑定工具
_INTEROP_CACHE: dict = {}


def _sw_install_dirs() -> list[str]:
    """候选 SolidWorks 安装目录（Interop DLL 所在地）。"""
    dirs: list[str] = []
    for env in ("SW_INSTALL_DIR", "SOLIDWORKS_DIR"):
        v = os.environ.get(env)
        if v:
            dirs.append(v)
    try:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key in (
                r"SOFTWARE\SolidWorks\SOLIDWORKS 2025\Setup",
                r"SOFTWARE\SolidWorks\SOLIDWORKS 2024\Setup",
                r"SOFTWARE\SolidWorks\SOLIDWORKS 2023\Setup",
                r"SOFTWARE\SolidWorks\SOLIDWORKS 2022\Setup",
            ):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        p, _ = winreg.QueryValueEx(k, "SolidWorks Folder")
                        if p:
                            dirs.append(p)
                except OSError:
                    continue
    except Exception:                                    # noqa: BLE001
        pass
    for letter in ("C", "D", "E", "F"):
        dirs.append(f"{letter}:\\SW2025\\SOLIDWORKS")
        dirs.append(f"{letter}:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS")
    return dirs


def _load_interop_type():
    """加载 `SolidWorks.Interop.sldworks.ISldWorks` 的 .NET 类型。"""
    if "type" in _INTEROP_CACHE:
        return _INTEROP_CACHE["type"]

    found = None
    for d in _sw_install_dirs():
        cand = os.path.join(d, "SolidWorks.Interop.sldworks.dll")
        if os.path.isfile(cand):
            found = d
            break
    if not found:
        _INTEROP_CACHE["type"] = None
        return None

    sldworks_dll = os.path.join(found, "SolidWorks.Interop.sldworks.dll")
    swconst_dll = os.path.join(found, "SolidWorks.Interop.swconst.dll")
    ps = (
        "$ErrorActionPreference='Stop';"
        f"[System.Reflection.Assembly]::LoadFrom('{swconst_dll}') | Out-Null;"
        f"$a=[System.Reflection.Assembly]::LoadFrom('{sldworks_dll}');"
        "$t=$a.GetType('SolidWorks.Interop.sldworks.ISldWorks');"
        "Write-Output $t.AssemblyQualifiedName"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=60,
        )
        name = (out.stdout or "").strip().splitlines()[-1]
    except Exception:                                    # noqa: BLE001
        name = ""

    if not name:
        _INTEROP_CACHE["type"] = None
        return None

    # 用 pythonnet 打通 .NET；未安装则早期绑定不可用
    try:
        import clr  # noqa: F401  # pythonnet

        clr.AddReference(sldworks_dll)
        clr.AddReference(swconst_dll)
        import System

        t = System.Type.GetType(name)
        _INTEROP_CACHE["type"] = t
        return t
    except Exception:                                    # noqa: BLE001
        _INTEROP_CACHE["type"] = None
        return None


def _dispatch_typed(interop_type):
    """从运行中的 SW 实例取得早期绑定代理。"""
    try:
        import System
        from System.Runtime.InteropServices import Marshal

        progid = System.Type.GetTypeFromProgID("SldWorks.Application")
        obj = Marshal.GetActiveObject("SldWorks.Application")
        return Marshal.GetTypedObjectForIUnknown(
            Marshal.GetIUnknownForObject(obj), interop_type
        )
    except Exception as exc:                             # noqa: BLE001
        raise SWError(f"早期绑定代理获取失败（需 pythonnet）：{exc}") from exc
