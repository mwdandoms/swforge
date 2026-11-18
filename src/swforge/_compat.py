# -*- coding: utf-8 -*-
"""跨 Python 版本兼容垫片。

swforge 原本声明 ``requires-python >= 3.10``，但实测代码几乎没用到 3.10 特性
（运行期零处 ``X | Y``、无 match、无 zip(strict=)）。真正的 3.10 专属 API 只有
一个：

    tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # 3.10 新增

SolidWorks 2018/2019 的机器常常只有 Python 3.8/3.9，为了让这些机器能直接装，
这里把该参数按版本降级处理。装不上旧 Python 时才考虑便携解释器方案。

用法：

    from ._compat import temp_dir
    with temp_dir('swforge_') as work:
        ...
"""
from __future__ import annotations

import sys
import tempfile

#: 3.10 才有 ignore_cleanup_errors；旧版直接不传
_IGNORE_KW = {"ignore_cleanup_errors": True} if sys.version_info >= (3, 10) else {}

#: 实测可用的最低 Python 版本
MIN_PYTHON = (3, 8)


def temp_dir(prefix: str = "swforge_") -> tempfile.TemporaryDirectory:
    """跨版本的 TemporaryDirectory。

    3.10+ 传 ``ignore_cleanup_errors=True``（Windows 上文件被 SolidWorks 短暂占用时
    不会因为清理失败而抛异常）；3.8/3.9 不支持该参数，退回普通行为。
    """
    return tempfile.TemporaryDirectory(prefix=prefix, **_IGNORE_KW)


def python_supported() -> bool:
    """本解释器是否满足 swforge 的最低要求。"""
    return sys.version_info[:2] >= MIN_PYTHON
