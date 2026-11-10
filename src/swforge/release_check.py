# -*- coding: utf-8 -*-
"""发版一致性检查 —— 回答「本地 / GitHub / PyPI 三者一致吗」。

为什么需要这个
--------------
v1.1.0 就栽在这上面：标签打完（`677ec07`）之后又改了源码：

    src/swforge/drawing.py   出图缩放修复
    src/swforge/cli.py       --json 路径修复

但没重新发版。结果 PyPI 上的 1.1.0 **缺两个用户可见的修复**，
README 说能用，装上其实是坏的。**没有任何机制会提醒这件事。**

这个脚本把「检查」变成一条命令：

    swforge release-check

检查四件事
----------
1. 工作区有没有未提交改动
2. 本地有没有未推送的提交
3. src/ 自上个标签以来有没有改动（有改动却还是同一个版本号 = 漏发）
4. PyPI 上的最新版本号与本地是否一致

第 3 条是核心 —— 它专门抓「改了代码但忘了发版」这种情况。

退出码
------
    0  一致
    1  发现问题
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request

__all__ = ["check_release", "PACKAGE"]

PACKAGE = "swforge"
PYPI_JSON = "https://pypi.org/pypi/{pkg}/json"


# ---------------------------------------------------------------- 工具
def _run(args, cwd) -> tuple[int, str]:
    """跑一条 git 命令，返回 (退出码, 输出)。"""
    try:
        p = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return -1, "找不到 git"
    except subprocess.TimeoutExpired:
        return -2, "git 命令超时"
    except Exception as exc:                           # noqa: BLE001
        return -3, f"{type(exc).__name__}: {exc}"


def _repo_root() -> str:
    """从本文件的路径往上找仓库根（含 pyproject.toml 的目录）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isfile(os.path.join(here, "pyproject.toml")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return os.getcwd()


def _local_version(root: str) -> str:
    """读 pyproject.toml 里的版本号。"""
    p = os.path.join(root, "pyproject.toml")
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8") as fh:
        m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
    return m.group(1) if m else ""


def _pypi_version(pkg: str = PACKAGE, timeout: int = 20) -> tuple[str, str]:
    """查 PyPI 上的最新版本。返回 (版本, 错误说明)。

    注意：`/pypi/<pkg>/json` 这个端点有 CDN 缓存，可能滞后几分钟。
    所以版本比对本身是「尽力而为」，查不到不算硬失败。
    """
    try:
        req = urllib.request.Request(
            PYPI_JSON.format(pkg=pkg), headers={"User-Agent": "swforge-release-check"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        return str(data.get("info", {}).get("version") or ""), ""
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "", "PyPI 上还没有这个包"
        return "", f"HTTP {e.code}"
    except Exception as exc:                           # noqa: BLE001
        return "", f"{type(exc).__name__}: {str(exc)[:60]}"


# ---------------------------------------------------------------- 主检查
def check_release(root: str | None = None,
                  pkg: str = PACKAGE,
                  online: bool = True) -> dict:
    """跑全部一致性检查。

    返回 `{ok, issues:[...], warnings:[...], facts:{...}}`
    """
    root = root or _repo_root()
    issues: list[str] = []
    warnings: list[str] = []
    facts: dict = {}

    version = _local_version(root)
    facts["local_version"] = version
    if not version:
        issues.append("读不到 pyproject.toml 里的版本号")

    # ---- 1. 工作区
    code, out = _run(["git", "status", "--porcelain"], root)
    if code != 0:
        warnings.append(f"查不了 git 状态：{out.strip()[:80]}")
    else:
        dirty = [ln for ln in out.splitlines() if ln.strip()]
        facts["dirty_files"] = len(dirty)
        if dirty:
            issues.append(f"工作区有 {len(dirty)} 个未提交改动")

    # ---- 2. 未推送的提交
    code, out = _run(["git", "log", "--oneline", "origin/HEAD..HEAD"], root)
    if code != 0:
        code, out = _run(["git", "log", "--oneline", "origin/main..HEAD"], root)
    if code == 0:
        unpushed = [ln for ln in out.splitlines() if ln.strip()]
        facts["unpushed"] = len(unpushed)
        if unpushed:
            issues.append(f"有 {len(unpushed)} 个提交没推到远端")

    # ---- 3. 自上个标签以来 src/ 有没有改动（核心检查）
    code, out = _run(["git", "describe", "--tags", "--abbrev=0"], root)
    last_tag = out.strip() if code == 0 else ""
    facts["last_tag"] = last_tag
    if not last_tag:
        warnings.append("仓库没有任何标签，跳过「改了源码没发版」检查")
    else:
        tag_ver = last_tag.lstrip("v")
        facts["tag_version"] = tag_ver

        code, out = _run(["git", "diff", "--name-only", f"{last_tag}..HEAD", "--", "src/"], root)
        if code == 0:
            changed = [ln for ln in out.splitlines() if ln.strip()]
            facts["src_changed_since_tag"] = changed

            # 关键区分：
            #   源码改了 + 版本号没动  -> 错误（漏发，PyPI 上的包缺修复）
            #   源码改了 + 版本号已升  -> 提醒（正常在准备发版，等打新标签即可）
            #   源码没改 + 版本号没动  -> 正常
            version_bumped = bool(tag_ver and version and tag_ver != version)

            if changed and not version_bumped:
                issues.append(
                    f"**{len(changed)} 个源码文件在 {last_tag} 之后改过，"
                    f"但版本号还是 {version}** —— "
                    f"PyPI 上的 {tag_ver} 不包含这些修复"
                )
                for f in changed[:8]:
                    issues.append(f"     {f}")
                issues.append(
                    f"     处理：把版本号升到 {tag_ver} 之后的新版本，"
                    f"打标签并发布；或者确认这些改动不需要发版")
            elif changed and version_bumped:
                warnings.append(
                    f"{len(changed)} 个源码在 {last_tag} 之后改过，版本号已升到 {version}"
                    f" —— 正常，等打完 v{version} 标签发布即可"
                )
                for f in changed[:5]:
                    warnings.append(f"     {f}")

    # ---- 4. PyPI
    if online:
        remote_ver, err = _pypi_version(pkg)
        facts["pypi_version"] = remote_ver
        facts["pypi_error"] = err
        if err:
            warnings.append(f"查不到 PyPI 版本（{err}）")
        elif remote_ver and version and remote_ver != version:
            warnings.append(
                f"PyPI 最新是 {remote_ver}，本地是 {version}"
                f"（可能刚发布有缓存延迟，也可能确实没发）"
            )

    return {
        "ok": not issues,
        "package": pkg,
        "repo": root,
        "version": version,
        "facts": facts,
        "issues": issues,
        "warnings": warnings,
    }


def format_report(r: dict) -> str:
    """把结果排成人能读的样子。"""
    lines = []
    lines.append("")
    lines.append("=" * 62)
    lines.append(f"  发版一致性检查  ·  {r['package']} {r['version']}")
    lines.append("=" * 62)
    lines.append("")

    f = r.get("facts") or {}
    lines.append(f"  仓库        {r['repo']}")
    lines.append(f"  本地版本    {f.get('local_version') or '?'}")
    lines.append(f"  最近标签    {f.get('last_tag') or '(无)'}")
    if "pypi_version" in f:
        v = f.get("pypi_version") or "?"
        err = f.get("pypi_error") or ""
        lines.append(f"  PyPI 版本   {v}" + (f"  ({err})" if err else ""))
    changed = f.get("src_changed_since_tag") or []
    lines.append(f"  标签后改源  {len(changed)} 个文件")
    lines.append("")

    if r["issues"]:
        lines.append("  ❌ 发现问题：")
        for i in r["issues"]:
            lines.append(f"     {i}")
        lines.append("")
    if r["warnings"]:
        lines.append("  ⚠️  提醒：")
        for w in r["warnings"]:
            lines.append(f"     {w}")
        lines.append("")

    if r["ok"]:
        lines.append("  ✅ 一致 —— 本地、标签、PyPI 三方对得上")
    else:
        lines.append("  ❌ 不一致 —— 按上面的提示处理")
    lines.append("")
    return "\n".join(lines)
