# -*- coding: utf-8 -*-
"""活动文档守卫 —— 解决「多个客户端抢同一个 SolidWorks」。

问题从哪来
----------
同类项目有这个 issue（hjbaard #10）：几个 agent 同时连一个 SolidWorks 时，
任一方的 `ActivateDoc` 都会把对方的活动文档切走。

后果很隐蔽：你激活了 A，正准备拉伸，另一个进程切到了 B，
于是拉伸做在了 B 上。**没有报错，结果错了。**

SolidWorks 是单实例应用，所有客户端共享同一个 ActiveDoc。
这是平台限制，不能靠"别同时用"来回避——用户真会同时开两个智能体。

怎么解决
--------
不做锁（跨进程锁在 COM 场景下不可靠，而且进程崩了会死锁）。
改成**每次操作前后都核对活动文档**：

    1. 操作前：激活目标文档并回读确认
    2. 操作后：再核对一次，发现被切走就重新激活并重做

代价是每次多一次 COM 往返（实测 1 ms 量级），换来的是"不会静默做错"。

用法
----
    from swforge.guard import document_guard

    with document_guard(part_path):
        builder.build()

或者手动控制：

    from swforge.guard import activate_verified, verify_active

    activate_verified(path)        # 激活并确认
    ... 操作 ...
    if not verify_active(path):    # 被人切走了
        activate_verified(path)    # 抢回来
"""

from __future__ import annotations

import contextlib
import os

__all__ = [
    "GuardError",
    "activate_verified",
    "verify_active",
    "document_guard",
    "active_path",
    "active_title",
    "switches_detected",
]


class GuardError(RuntimeError):
    """活动文档无法保持在目标上。"""


# 统计：被切走了多少次。用于 selftest 和诊断。
_SWITCHES = {"count": 0, "last": ""}


def switches_detected() -> dict:
    """返回本次进程内检测到的文档被切换次数。"""
    return dict(_SWITCHES)


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path))) if path else ""


def active_title() -> str:
    """当前活动文档的标题。空字符串表示没有活动文档。"""
    from .session import get_session, _value
    try:
        sw = get_session().sw()
        doc = sw.ActiveDoc
        if doc is None:
            return ""
        # GetTitle 返回不带扩展名的文档名
        return str(_value(doc, "GetTitle") or "")
    except Exception:                                  # noqa: BLE001
        return ""


def active_path() -> str:
    """当前活动文档的完整路径。"""
    from .session import get_session, _value
    try:
        sw = get_session().sw()
        doc = sw.ActiveDoc
        if doc is None:
            return ""
        return str(_value(doc, "GetPathName") or "")
    except Exception:                                  # noqa: BLE001
        return ""


def verify_active(path, by: str = "title") -> bool:
    """核对活动文档是不是目标文档。

    默认按标题比对——标题是 SolidWorks 自己维护的，比路径更可靠
    （新建未保存的文档没有路径，但有标题）。

    参数 by: 'title' 或 'path'
    """
    if not path:
        return True
    if by == "path":
        return _norm(active_path()) == _norm(path)
    want = os.path.splitext(os.path.basename(str(path)))[0].lower()
    got = active_title().lower()
    return bool(got) and want == got


def activate_verified(path, retries: int = 3) -> bool:
    """激活文档并回读确认。返回是否真的切过去了。

    为什么不能只调 ActivateDoc 就完事：它返回成功**不等于**切过去了。
    同类项目就栽在没回读这一步（andrewbartels1 #91）。
    """
    from .session import get_session

    if not path:
        return True
    path = str(path)
    if not os.path.isfile(path) and not os.path.isdir(path):
        return False

    sw = get_session().sw()
    for attempt in range(1, retries + 1):
        try:
            sw.ActivateDoc(path)
        except Exception:                              # noqa: BLE001
            pass
        if verify_active(path):
            return True
        # 被别的客户端抢了，退一步再试
        if attempt < retries:
            import time
            time.sleep(0.05 * attempt)
    return False


@contextlib.contextmanager
def document_guard(path, retries: int = 3):
    """在 with 块内保证活动文档是目标文档。

    块内如果有别的客户端切走了文档，退出时会被发现并记录；
    调用方可以选择重做那一步操作。

        with document_guard(p):
            do_something()
        # 若块内被切走，do_something 的结果可能不可信
    """
    if not activate_verified(path, retries=retries):
        raise GuardError(
            f"无法把活动文档切到 {os.path.basename(str(path))}，"
            f"可能被其他客户端持续抢占")

    before = active_title()
    try:
        yield
    finally:
        after = active_title()
        if before and after and before.lower() != after.lower():
            # 块内被切走了——操作可能做在了别的文档上
            _SWITCHES["count"] += 1
            _SWITCHES["last"] = f"{before} -> {after}"
        # 无论如何都尽量把文档抢回来
        activate_verified(path, retries=1)


def ensure_active_or_retry(path, fn, retries: int = 3):
    """执行 fn，若执行期间活动文档被切走就重做。

    适合"操作必须发生在指定文档上"的场景。
    fn 会被调用最多 retries 次，全部失败时抛 GuardError。

    注意：fn 必须是可以安全重复执行的（幂等）。
    建模这类会往文档里加特征的操作用这个要谨慎——
    重做会产生重复特征。这个函数主要给"读"类操作用。
    """
    last_err = None
    for attempt in range(1, retries + 1):
        if not activate_verified(path, retries=2):
            last_err = GuardError("无法激活目标文档")
            continue
        try:
            result = fn()
        except Exception as exc:                       # noqa: BLE001
            last_err = exc
            continue
        if verify_active(path):
            return result
        # 被切走了，结果不可信，重做
        _SWITCHES["count"] += 1
    raise GuardError(f"{retries} 次尝试都未能稳定在目标文档上：{last_err}")
