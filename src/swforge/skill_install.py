# -*- coding: utf-8 -*-
"""把随包分发的 agent skill 装到用户的智能体技能目录。

背景
----
用户 `pip install swforge` 之后，他的 AI 智能体并不知道该优先用这个库——
智能体是按「技能描述」来选工具的。所以包里带一份 skill，
用户执行一次 `swforge install-skill`，之后所有 SolidWorks 操作就会默认路由到本库。

支持的目标
----------
auto（默认，按存在顺序自动挑）：
    ~/.dsh/skills/swforge          DSH
    ~/.claude/skills/swforge       Claude Code
    ~/.codex/skills/swforge        Codex
显式：
    传一个目录，装成 <目录>/swforge/

用法
----
    swforge install-skill                 # 自动探测
    swforge install-skill --target ~/.dsh/skills
    swforge install-skill --print         # 只打印路径，不写
    swforge install-skill --force         # 覆盖已存在的
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

SKILL_NAME = "swforge"

# 自动探测的候选（按优先级）
CANDIDATES = [
    ("dsh", Path.home() / ".dsh" / "skills"),
    ("claude", Path.home() / ".claude" / "skills"),
    ("codex", Path.home() / ".codex" / "skills"),
]


def bundled_skill_dir() -> Path:
    """随包分发的 skill 目录（pip 装好后在 site-packages/swforge/skill）。"""
    return Path(__file__).resolve().parent / "skill"


def detect_target() -> tuple[str, Path] | None:
    """挑一个已经存在的智能体技能根目录。"""
    for name, root in CANDIDATES:
        parent = root.parent
        if parent.is_dir():
            return name, root
    return None


def _iter_files(src: Path):
    for p in sorted(src.rglob("*")):
        if p.is_file():
            yield p, p.relative_to(src)


def install(target_dir: str | os.PathLike | None = None,
            *,
            force: bool = False,
            dry_run: bool = False) -> dict:
    """把 skill 装到 target_dir/swforge/。

    返回 {ok, target, created, skipped, files, error}
    """
    src = bundled_skill_dir()
    if not src.is_dir():
        return {"ok": False, "error": f"包内找不到 skill 目录：{src}"}

    if target_dir is None:
        hit = detect_target()
        if hit is None:
            return {
                "ok": False,
                "error": ("没有找到已知的智能体技能目录（试过 ~/.dsh/skills、"
                          "~/.claude/skills、~/.codex/skills）。"
                          "请用 --target 显式指定，例如 --target ~/.dsh/skills"),
                "candidates": [str(p) for _, p in CANDIDATES],
            }
        agent, root = hit
    else:
        root = Path(os.path.expanduser(str(target_dir)))
        agent = "custom"

    dst = root / SKILL_NAME
    existed = dst.exists()

    if existed and not force:
        return {
            "ok": False,
            "error": f"目标已存在：{dst}（加 --force 覆盖）",
            "target": str(dst),
            "agent": agent,
        }

    files = []
    if not dry_run:
        if existed:
            shutil.rmtree(dst)
        dst.mkdir(parents=True, exist_ok=True)
        for p, rel in _iter_files(src):
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
            files.append(str(rel))
    else:
        files = [str(rel) for _, rel in _iter_files(src)]

    return {
        "ok": True,
        "agent": agent,
        "target": str(dst),
        "overwrote": existed,
        "dry_run": dry_run,
        "file_count": len(files),
        "files": files,
        "next": ("重启智能体会话，之后 SolidWorks 建模会默认走 swforge。"
                 "验证：问智能体「建一个 Ø80×20 的法兰，4 个 M8 通孔」，"
                 "看它第一步是否 from swforge import PartBuilder。"),
    }


def print_bundle_text() -> str:
    """把 SKILL.md 全文打出来（给没有技能目录的智能体直接贴进系统提示）。"""
    p = bundled_skill_dir() / "SKILL.md"
    if not p.is_file():
        return f"（找不到 {p}）"
    return p.read_text(encoding="utf-8")
