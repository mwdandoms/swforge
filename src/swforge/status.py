# -*- coding: utf-8 -*-
"""`swforge status` —— 一条命令回答「现在有什么在等我」。

为什么需要它
------------
这个项目出过一次很具体的事故：v0.9.1 的一个发布 run 卡在
「等待批准」状态，从下午 15:44 一直挂到第二天早上。
这期间仓库看起来一切正常，PyPI 上版本也在，**没有任何地方提示有东西在等人**。

同类问题还有：源码改了但没发版（v1.1.0）、发布停在审批环节、
某个 workflow 红了没人看。

`status` 把这些检查合成一次查询，输出固定三段：

    本地 / 远端 / 版本       —— 代码状态
    CI / 待批准 / 卡住的 run  —— 流水线状态   ← 事故就出在这一段
    需要你操作               —— 如果有，写清楚是什么

最后那段是重点。**没有东西要你做时，它会明确写「无」。**

用法
----
    swforge status                  # 完整检查
    swforge status --offline        # 只查本地和 PyPI，不查 GitHub
    swforge status --json           # 给程序读

退出码
------
    0   一切正常
    1   有需要你处理的事项
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request

__all__ = ["check_status", "format_status", "github_token", "PACKAGE"]

PACKAGE = "swforge"
GH_API = "https://api.github.com"


# ---------------------------------------------------------------- 基础
def _run(args, cwd, timeout=60) -> tuple[int, str]:
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return -1, "找不到 git"
    except subprocess.TimeoutExpired:
        return -2, "超时"
    except Exception as exc:                           # noqa: BLE001
        return -3, f"{type(exc).__name__}: {exc}"


def _repo_root() -> str:
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
    p = os.path.join(root, "pyproject.toml")
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8") as fh:
        m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
    return m.group(1) if m else ""


def github_token() -> tuple[str, str]:
    """找 GitHub token。返回 (token, 来源说明)。

    按可靠性排序：
      1. 环境变量 GITHUB_TOKEN / GH_TOKEN
      2. `gh auth token`（GitHub CLI）
      3. git credential helper（push 用的那套凭据）

    拿不到不是错误——`status` 会降级成只查公开信息。
    """
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "SWFORGE_GH_TOKEN"):
        v = os.environ.get(name, "").strip()
        if v:
            return v, f"环境变量 {name}"

    code, out = _run(["gh", "auth", "token"], os.getcwd(), timeout=20)
    if code == 0 and out.strip() and "\n" not in out.strip():
        return out.strip(), "gh CLI"

    payload = "protocol=https\nhost=github.com\n\n"
    try:
        p = subprocess.run(
            ["git", "credential", "fill"], input=payload, capture_output=True,
            text=True, timeout=20, encoding="utf-8", errors="replace")
        for line in (p.stdout or "").splitlines():
            if line.startswith("password="):
                return line[len("password="):].strip(), "git credential"
    except Exception:                                  # noqa: BLE001
        pass
    return "", ""


def _gh_get(path: str, token: str, timeout: int = 30):
    """GET 一个 GitHub API 路径。返回 (data, err)。"""
    req = urllib.request.Request(
        GH_API + path,
        headers={
            "User-Agent": "swforge-status",
            "Accept": "application/vnd.github+json",
            **({"Authorization": f"token {token}"} if token else {}),
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), ""
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as exc:                           # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:60]}"


def _pypi_version(pkg: str = PACKAGE, timeout: int = 20) -> tuple[str, str]:
    try:
        req = urllib.request.Request(
            f"https://pypi.org/pypi/{pkg}/json",
            headers={"User-Agent": "swforge-status"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
        return str(d.get("info", {}).get("version") or ""), ""
    except urllib.error.HTTPError as e:
        return "", f"HTTP {e.code}"
    except Exception as exc:                           # noqa: BLE001
        return "", f"{type(exc).__name__}"


def _slug(root: str) -> str:
    """从 origin 的 URL 里取 owner/repo。"""
    code, out = _run(["git", "remote", "get-url", "origin"], root, timeout=20)
    if code != 0:
        return ""
    m = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$", out.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else ""


# ---------------------------------------------------------------- 主检查
def check_status(root: str | None = None,
                 pkg: str = PACKAGE,
                 online: bool = True) -> dict:
    """跑全部检查。返回结构化结果。"""
    root = root or _repo_root()
    facts: dict = {}
    todo: list[dict] = []          # 需要人做的事，最重要
    warn: list[str] = []

    # ---- 本地 Git
    code, out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
    facts["branch"] = out.strip() if code == 0 else ""

    code, out = _run(["git", "rev-parse", "HEAD"], root)
    facts["head"] = out.strip()[:7] if code == 0 else ""

    code, out = _run(["git", "status", "--porcelain"], root)
    dirty = [ln for ln in out.splitlines() if ln.strip()] if code == 0 else []
    facts["dirty"] = len(dirty)

    code, out = _run(["git", "describe", "--tags", "--abbrev=0"], root)
    facts["tag"] = out.strip() if code == 0 else ""

    facts["version"] = _local_version(root)

    code, out = _run(["git", "log", "--oneline", "origin/HEAD..HEAD"], root)
    if code != 0:
        code, out = _run(["git", "log", "--oneline", "origin/main..HEAD"], root)
    unpushed = [ln for ln in out.splitlines() if ln.strip()] if code == 0 else []
    facts["unpushed"] = len(unpushed)

    if dirty:
        warn.append(f"工作区有 {len(dirty)} 个未提交改动")
    if unpushed:
        todo.append({"what": f"{len(unpushed)} 个提交没推到 GitHub",
                     "how": "git push"})

    # ---- 源码自上个标签以来的改动（漏发检查）
    if facts["tag"]:
        code, out = _run(["git", "diff", "--name-only",
                          f"{facts['tag']}..HEAD", "--", "src/"], root)
        changed = [ln for ln in out.splitlines() if ln.strip()] if code == 0 else []
        facts["src_changed"] = len(changed)
        tag_ver = facts["tag"].lstrip("v")
        if changed and tag_ver == facts["version"]:
            todo.append({
                "what": f"{len(changed)} 个源码文件在 {facts['tag']} 之后改过，"
                        f"版本号还是 {facts['version']} —— PyPI 上的包缺这些修复",
                "how": f"升版本号到 > {tag_ver}，打标签发布",
            })
        elif changed:
            warn.append(f"{len(changed)} 个源码改动待发版（版本号已升到 "
                        f"{facts['version']}，等打 v{facts['version']} 标签）")

    # ---- PyPI
    if online:
        ver, err = _pypi_version(pkg)
        facts["pypi"] = ver
        facts["pypi_err"] = err
        if err:
            warn.append(f"查不到 PyPI（{err}）")
        elif ver and facts["version"] and ver != facts["version"]:
            warn.append(f"PyPI 最新 {ver}，本地 {facts['version']}"
                        f"（可能缓存延迟，也可能没发）")

    # ---- GitHub：CI + 待批准
    if online:
        slug = _slug(root)
        facts["repo"] = slug
        token, src = github_token()
        facts["token_source"] = src
        if not slug:
            warn.append("取不到 GitHub 仓库地址（没有 origin？）")
        elif not token:
            warn.append("没有 GitHub token —— 查不了 CI 和待批准项，"
                        "设 GITHUB_TOKEN 环境变量后可用")
        else:
            runs, err = _gh_get(
                f"/repos/{slug}/actions/runs?per_page=8", token)
            if err:
                warn.append(f"查 CI 失败：{err}")
            else:
                items = (runs or {}).get("workflow_runs") or []
                facts["runs"] = [
                    {"name": r.get("name"), "status": r.get("status"),
                     "conclusion": r.get("conclusion"),
                     "branch": r.get("head_branch"),
                     "sha": (r.get("head_sha") or "")[:7],
                     "url": r.get("html_url"),
                     "created": r.get("created_at")}
                    for r in items
                ]
                failed = [r for r in items if r.get("conclusion") == "failure"]
                facts["ci_failed"] = len(failed)
                if failed:
                    f0 = failed[0]
                    warn.append(f"最近有 {len(failed)} 个 workflow 失败"
                                f"（最新：{f0.get('name')} "
                                f"{(f0.get('head_sha') or '')[:7]}）")

            # 待批准的 run —— 这是本项目出过事故的地方
            waiting, werr = _gh_get(
                f"/repos/{slug}/actions/runs?status=waiting&per_page=20", token)
            if not werr:
                wl = (waiting or {}).get("workflow_runs") or []
                facts["waiting"] = [
                    {"name": r.get("name"), "branch": r.get("head_branch"),
                     "sha": (r.get("head_sha") or "")[:7],
                     "created": r.get("created_at"),
                     "url": r.get("html_url")}
                    for r in wl
                ]
                for r in wl:
                    todo.append({
                        "what": f"workflow「{r.get('name')}」卡在等待批准"
                                f"（{r.get('head_branch')} "
                                f"{(r.get('head_sha') or '')[:7]}）",
                        "how": f"批准 {r.get('html_url')}",
                    })

    return {
        "ok": not todo,
        "package": pkg,
        "repo_dir": root,
        "facts": facts,
        "todo": todo,
        "warnings": warn,
    }


def format_status(s: dict) -> str:
    """排版。三段：代码状态 / 流水线状态 / 需要你操作。"""
    f = s.get("facts") or {}
    L: list[str] = []
    L.append("")
    L.append("=" * 64)
    L.append(f"  swforge status  ·  {s.get('package')} {f.get('version') or '?'}")
    L.append("=" * 64)
    L.append("")

    # ---- 代码
    L.append("  代码")
    L.append(f"    分支 / HEAD     {f.get('branch') or '?'} / {f.get('head') or '?'}")
    L.append(f"    未提交改动      {f.get('dirty', 0)}")
    L.append(f"    未推送提交      {f.get('unpushed', 0)}")
    L.append(f"    版本 / 标签     {f.get('version') or '?'} / {f.get('tag') or '(无)'}")
    if "src_changed" in f:
        L.append(f"    标签后改源      {f['src_changed']} 个文件")
    if "pypi" in f:
        L.append(f"    PyPI 最新       {f.get('pypi') or '?'}")
    L.append("")

    # ---- 流水线
    L.append("  流水线")
    if f.get("repo"):
        L.append(f"    GitHub 仓库     {f['repo']}")
    if "waiting" in f:
        L.append(f"    等待批准        {len(f['waiting'])} 个")
    if "ci_failed" in f:
        L.append(f"    最近失败        {f['ci_failed']} 个")
    elif "runs" in f:
        L.append(f"    最近失败        0 个")
    runs = f.get("runs") or []
    for r in runs[:4]:
        ok = "✓" if r.get("conclusion") == "success" else (
            "✗" if r.get("conclusion") == "failure" else "·")
        L.append(f"      [{ok}] {str(r.get('name'))[:26]:<26} "
                 f"{str(r.get('branch'))[:10]:<10} {r.get('sha')}")
    if not f.get("runs") and not f.get("repo"):
        L.append("    （未查——离线模式或没有 token）")
    L.append("")

    # ---- 需要你操作（重点）
    todo = s.get("todo") or []
    if todo:
        L.append("  🔴 需要你操作")
        for i, t in enumerate(todo, 1):
            L.append(f"    {i}. {t['what']}")
            L.append(f"       → {t['how']}")
    else:
        L.append("  ✅ 需要你操作：无")
    L.append("")

    warns = s.get("warnings") or []
    if warns:
        L.append("  ⚠️  提醒")
        for w in warns:
            L.append(f"    · {w}")
        L.append("")

    L.append("=" * 64)
    L.append("  " + ("✅ 一切正常" if not todo else "🔴 有事项等你处理"))
    L.append("=" * 64)
    L.append("")
    return "\n".join(L)
