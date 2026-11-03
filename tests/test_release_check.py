# -*- coding: utf-8 -*-
"""发版一致性检查的测试。

重点不是测「能跑」，是测**能不能抓住 v1.1.0 那种情况**：
标签打完又改源码，版本号没动，导致 PyPI 上的包缺修复。
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from swforge.release_check import check_release, format_report, _local_version  # noqa: E402


def _git(cwd, *args):
    """在临时仓库里跑 git；没有 git 就跳过。"""
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
    """造一个最小的 git 仓库：pyproject + src/。"""
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


# ---------------------------------------------------------------- 基础
def test_reads_version_from_pyproject(repo):
    assert _local_version(str(repo)) == "1.0.0"


def test_clean_repo_with_matching_tag_passes(repo):
    _git(repo, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    r = check_release(str(repo), online=False)
    ver_issue = [i for i in r["issues"]
                 if "源码文件在" in i or "标签 v" in i]
    assert not ver_issue, f"干净仓库不该报版本问题：{ver_issue}"


# ---------------------------------------------------------------- 核心：抓漏发
def test_detects_source_changed_after_tag(repo):
    """复现 v1.1.0 的 bug：打完标签又改了源码，版本号没动。

    这是这个工具存在的全部理由。抓不到就等于没做。
    """
    _git(repo, "tag", "-a", "v1.0.0", "-m", "v1.0.0")

    # 标签之后改源码，但不动版本号
    (repo / "src" / "pkg" / "__init__.py").write_text("# changed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix something")

    r = check_release(str(repo), online=False)
    assert not r["ok"], "改了源码没发版，必须报错"
    joined = " ".join(r["issues"])
    assert "个源码文件在" in joined, f"没指出源码改动：{r['issues']}"
    assert "PyPI 上的" in joined, f"没说明后果：{r['issues']}"
    assert r["facts"]["src_changed_since_tag"], "facts 里没记录改动的文件"


def test_source_change_with_version_bump_passes(repo):
    """改了源码**并且**升了版本号，是正确流程，不该报错。"""
    _git(repo, "tag", "-a", "v1.0.0", "-m", "v1.0.0")

    (repo / "src" / "pkg" / "__init__.py").write_text("# changed\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.1"\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bump")

    r = check_release(str(repo), online=False)
    ver_issues = [i for i in r["issues"] if "源码文件在" in i]
    assert not ver_issues, f"升了版本号就不该报漏发：{ver_issues}"


def test_tag_version_mismatch_is_a_warning(repo):
    """标签 v1.0.0 但版本号已升到 9.9.9，源码也改过。

    这是**正常的「准备发版中」状态**——版本号升了，等打新标签就行。
    所以算提醒不算错误。判错会让每次开发中途都报红，工具就没人看了。
    """
    _git(repo, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    (repo / "src" / "pkg" / "__init__.py").write_text("# y\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "9.9.9"\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bump")

    r = check_release(str(repo), online=False)
    # 版本号一致性问题不该出现在 issues 里
    assert not [i for i in r["issues"] if "源码文件在" in i], \
        f"升了版本号却判成漏发：{r['issues']}"
    joined = " ".join(r["warnings"])
    assert "9.9.9" in joined, f"没提醒版本号已升：{r['warnings']}"


# ---------------------------------------------------------------- 其他检查
def test_detects_dirty_working_tree(repo):
    _git(repo, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    (repo / "src" / "pkg" / "__init__.py").write_text("dirty\n", encoding="utf-8")
    r = check_release(str(repo), online=False)
    assert any("未提交改动" in i for i in r["issues"])


def test_no_tags_is_a_warning_not_an_error(repo):
    """没有标签时不该硬失败——本地开发阶段很正常。"""
    r = check_release(str(repo), online=False)
    assert any("没有任何标签" in w for w in r["warnings"])
    ver_issues = [i for i in r["issues"] if "源码文件在" in i]
    assert not ver_issues


def test_offline_skips_pypi(repo):
    _git(repo, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    r = check_release(str(repo), online=False)
    assert "pypi_version" not in r["facts"]


# ---------------------------------------------------------------- 输出
def test_report_mentions_issues(repo):
    _git(repo, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    (repo / "src" / "pkg" / "__init__.py").write_text("# x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "x")
    r = check_release(str(repo), online=False)
    text = format_report(r)
    assert "发版一致性检查" in text
    assert "❌" in text
    assert "不一致" in text
