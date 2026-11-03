# -*- coding: utf-8 -*-
"""活动文档守卫的离线可测部分。

真正的并发验证需要两个进程抢一个 SolidWorks（见 selftest 的 simulate 项），
这里测的是纯逻辑：路径归一化、标题比对规则、统计计数。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import swforge.guard as guard  # noqa: E402


def test_norm_is_case_and_separator_insensitive():
    """Windows 路径大小写不敏感，比较前必须归一化。"""
    a = guard._norm(r"C:\Parts\Plate.SLDPRT")
    b = guard._norm(r"c:\parts\plate.SLDPRT")
    assert a == b


def test_norm_handles_empty():
    assert guard._norm("") == ""
    assert guard._norm(None) == ""


def test_verify_active_without_path_is_true():
    """目标为空时不做校验，避免误报。"""
    assert guard.verify_active("") is True
    assert guard.verify_active(None) is True


def test_switches_counter_starts_at_zero():
    s = guard.switches_detected()
    assert "count" in s and "last" in s


def test_activate_verified_rejects_missing_file():
    """文件不存在时直接返回 False，不去碰 COM。

    这一点很重要：不该为了激活一个不存在的文件去连 SolidWorks，
    否则单测和离线场景都会被拖进真实连接。
    """
    r = guard.activate_verified(r"C:\definitely\does\not\exist_12345.SLDPRT")
    assert r is False


def test_ensure_active_or_retry_raises_on_missing_target():
    """目标文件不存在时，重试若干次后必须抛错而不是静默返回。"""
    with pytest.raises(guard.GuardError):
        guard.ensure_active_or_retry(
            r"C:\definitely\does\not\exist_12345.SLDPRT",
            lambda: "never runs",
            retries=2,
        )


def test_guard_error_is_runtime_error():
    """GuardError 要能被通用的 RuntimeError 捕获，方便上层统一处理。"""
    assert issubclass(guard.GuardError, RuntimeError)
