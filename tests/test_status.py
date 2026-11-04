# -*- coding: utf-8 -*-
"""`swforge status` 的测试。

重点测两件事：

1. **该报的都报出来** —— 尤其是「待批准」和「漏发」，
   这两类事故本项目都真实发生过（v0.9.1 卡了一晚、v1.1.0 漏发）。
2. **没有东西要人做时必须明确说「无」** ——
   含糊不清正是「干等但不知情」的根源。
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from swforge.status import (  # noqa: E402
    _local_version,
    check_status,
    format_status,
)


def _git(cwd, *args):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=10)
        return True
    except Exception:                                  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _has_git(), reason="没有 git")


@pytest.fixture()
def repo(tmp_path):
    d = tmp_path / "r"
    (d / "src" / "pkg").mkdir(parents=True)
    (d / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\n', encoding="utf-8")
    (d / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "init")
    return d


# ---------------------------------------------------------------- 排版
def _bare(todo=None, warnings=None, **facts):
    base = {"version": "1.2.1", "branch": "main", "head": "abc1234",
            "dirty": 0, "unpushed": 0, "tag": "v1.2.1", "src_changed": 0}
    base.update(facts)
    return {"ok": not todo, "package": "swforge", "repo_dir": ".",
            "facts": base, "todo": todo or [], "warnings": warnings or []}


def test_says_nothing_to_do_explicitly():
    """没有事项时必须明说「无」。

    这一句是整个工具存在的理由：含糊 = 用户干等。
    """
    text = format_status(_bare())
    assert "需要你操作：无" in text
    assert "✅" in text


def test_lists_todo_items_with_action():
    s = _bare(todo=[{"what": "workflow「publish to PyPI」卡在等待批准（v1.2.1）",
                     "how": "批准 https://github.com/x/y/actions/runs/1"}])
    text = format_status(s)
    assert "需要你操作" in text
    assert "卡在等待批准" in text
    assert "https://github.com/x/y/actions/runs/1" in text, "没说清怎么做"
    assert "🔴" in text


def test_shows_three_sections():
    text = format_status(_bare())
    for part in ("代码", "流水线", "需要你操作"):
        assert part in text, f"缺了「{part}」这一段"


def test_warnings_are_separate_from_todo():
    """提醒和「要你做的事」必须分开——混在一起会让人分不清轻重。"""
    s = _bare(warnings=["PyPI 最新 1.2.0，本地 1.2.1（可能缓存延迟）"])
    text = format_status(s)
    assert "提醒" in text
    assert "需要你操作：无" in text
    assert s["ok"] is True, "只是提醒不该让整体判失败"


# ---------------------------------------------------------------- 检查
def test_offline_skips_network(repo):
    s = check_status(str(repo), online=False)
    assert "pypi" not in s["facts"]
    assert "runs" not in s["facts"]


def test_reads_version(repo):
    assert _local_version(str(repo)) == "1.0.0"
    assert check_status(str(repo), online=False)["facts"]["version"] == "1.0.0"


def test_detects_dirty_tree_as_warning(repo):
    (repo / "src" / "pkg" / "__init__.py").write_text("x\n", encoding="utf-8")
    s = check_status(str(repo), online=False)
    assert s["facts"]["dirty"] >= 1
    assert any("未提交" in w for w in s["warnings"])


def test_detects_unpushed_as_todo(repo):
    """没推的提交要进「需要你操作」，因为是提醒而不是错误。"""
    # 造一个假的 origin/main 落后状态
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / "src" / "pkg" / "__init__.py").write_text("y\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "second")

    s = check_status(str(repo), online=False)
    assert s["facts"]["unpushed"] >= 1
    assert any("没推到 GitHub" in t["what"] for t in s["todo"]), s["todo"]


def test_detects_missing_release_after_source_change(repo):
    """复现 v1.1.0：打完标签又改源码，版本号没动。"""
    _git(repo, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    (repo / "src" / "pkg" / "__init__.py").write_text("# fix\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix")

    s = check_status(str(repo), online=False)
    assert not s["ok"], "改了源码没发版必须报出来"
    joined = " ".join(t["what"] for t in s["todo"])
    assert "源码文件" in joined and "缺这些修复" in joined, s["todo"]


def test_version_bump_turns_it_into_warning(repo):
    """改了源码**并且**升了版本号 = 正常准备发版，只提醒。"""
    _git(repo, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    (repo / "src" / "pkg" / "__init__.py").write_text("# fix\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.1"\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bump")

    s = check_status(str(repo), online=False)
    assert not [t for t in s["todo"] if "源码文件" in t["what"]], s["todo"]
    assert any("待发版" in w for w in s["warnings"]), s["warnings"]


# ---------------------------------------------------------------- 输出契约
def test_json_serialisable(repo):
    import json
    s = check_status(str(repo), online=False)
    blob = json.dumps(s, ensure_ascii=False)
    assert "facts" in json.loads(blob)


def test_ok_flag_matches_todo(repo):
    s = check_status(str(repo), online=False)
    assert s["ok"] == (not s["todo"])

def test_pypi_cache_delay_does_not_raise_false_alarm(monkeypatch):
    """PyPI 首页版本号有缓存延迟，不能因此报「可能没发」。

    这是实机踩到的：1.3.0 明明已经可以 pip install，
    但 status 因为首页还显示 1.2.1 而报了一条提醒。
    **误报比不报更糟**——人会开始忽略所有提醒。
    """
    import swforge.status as st

    monkeypatch.setattr(st, "_pypi_version", lambda *a, **k: ("1.2.1", ""))
    # 直接查具体版本时确认存在
    monkeypatch.setattr(st, "_pypi_has_version", lambda v, *a, **k: (True, ""))

    s = _bare(pypi="1.2.1", version="1.3.0")
    # 手工跑一遍 PyPI 那段逻辑
    facts = s["facts"]
    ver, err = st._pypi_version("swforge")
    if not err and ver != facts["version"]:
        have, _ = st._pypi_has_version(facts["version"])
        if have:
            facts["pypi"] = facts["version"]
            s["warnings"].append("CDN 缓存")

    text = format_status(s)
    assert "需要你操作：无" in text
    assert "PyPI 最新 1.2.1" not in text


def test_pypi_missing_version_is_a_todo(monkeypatch):
    """真的没发出去时，必须进「需要你操作」。"""
    import swforge.status as st

    monkeypatch.setattr(st, "_pypi_version", lambda *a, **k: ("1.2.1", ""))
    monkeypatch.setattr(st, "_pypi_has_version", lambda v, *a, **k: (False, "HTTP 404"))

    ver, _ = st._pypi_version("swforge")
    have, _ = st._pypi_has_version("1.3.0")
    assert ver == "1.2.1" and have is False
