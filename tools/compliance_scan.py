# -*- coding: utf-8 -*-
"""发布前合规扫描 —— 拦住「把第三方素材 / 型材轮廓 / 厂商模型打进包」。

背景
====
用户的素材库里混有厂商提供的私人素材（亚德客、米思米等），这些**只能在本机用**，
绝不允许随 swforge 或任何发布包分发。swforge 本身只在运行时读本机目录
（``library.py`` 的 ``_default_roots()``），包内不含任何轮廓文件；
这个脚本是最后一道机器闸门，防止哪天有人顺手把素材塞进 ``assets/``。

判定分三级
----------
- **FAIL**  出现禁止分发的 CAD 二进制（零件 / 装配 / 型材轮廓 / 中间格式）
            → 直接拦住，不许发布
- **WARN**  出现厂商名称字样（文档里提到品牌名属正常引用，交人工判断）
            → 不拦，但要列出来
- **OK**    swforge 自制的 GB 图框模板（``.DRWDOT`` / ``.slddrt``）允许分发

用法
----
    python tools/compliance_scan.py <目录> [<目录> ...]
    python tools/compliance_scan.py <目录> --json
    python tools/compliance_scan.py <目录> --allow path/to/exception.sldprt

退出码：0 = 通过（可能有 WARN）；1 = 有 FAIL。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

#: 禁止随包分发的 CAD 二进制。这些是「素材」而非「程序」。
FORBIDDEN_EXT = {
    ".sldprt", ".sldasm", ".sldlfp", ".slddrw",          # SolidWorks 零件/装配/轮廓/图纸
    ".step", ".stp", ".iges", ".igs",                     # 通用交换格式
    ".x_t", ".x_b", ".sat", ".jt", ".3mf", ".stl",        # 其他 CAD 交换格式
    ".ipt", ".iam", ".catpart", ".catproduct",            # Inventor / CATIA
    ".prt", ".asm",                                       # NX / Creo
}

#: 允许分发的模板（swforge 自制的 GB 图框，是本项目产物，不是第三方素材）
ALLOWED_TEMPLATE_EXT = {".drwdot", ".slddrt"}

#: 厂商名称（文档里的品牌引用算正常，只 WARN 不拦）
VENDOR_NAMES = (
    "亚德客", "AirTAC", "米思米", "MISUMI", "怡合达",
    "Festo", "费斯托", "雄克", "Schunk", "上银", "HIWIN",
)

#: 单个文件超过这个体积就提示（发布包里不该有巨型二进制）
BIG_FILE_MB = 5.0

#: 不扫的目录
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "dist", "build"}


def scan(root: str, allow: set[str] | None = None) -> dict:
    allow = {os.path.normcase(os.path.abspath(p)) for p in (allow or set())}
    fails: list[dict] = []
    warns: list[dict] = []
    bigs: list[dict] = []
    templates = 0
    scanned = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            ext = os.path.splitext(fn)[1].lower()
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            scanned += 1

            if ext in ALLOWED_TEMPLATE_EXT:
                templates += 1
                continue
            if ext in FORBIDDEN_EXT:
                if os.path.normcase(os.path.abspath(p)) in allow:
                    warns.append({"kind": "allowed_exception", "path": rel, "bytes": size})
                else:
                    fails.append({"kind": "forbidden_cad", "path": rel, "bytes": size,
                                  "reason": f"{ext} 属于第三方素材，禁止随包分发"})
                continue
            if size > BIG_FILE_MB * 1024 * 1024:
                bigs.append({"path": rel, "mb": round(size / 1024 / 1024, 1)})
            # 文本类才查厂商名
            if ext in {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ps1", ".cs"}:
                try:
                    text = open(p, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                for name in VENDOR_NAMES:
                    if name in text:
                        warns.append({"kind": "vendor_mention", "path": rel, "name": name})

    return {
        "root": os.path.abspath(root),
        "scanned": scanned,
        "templates": templates,
        "fails": fails,
        "warns": warns,
        "big_files": bigs,
        "ok": not fails,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="发布前合规扫描：禁止第三方 CAD 素材随包分发")
    ap.add_argument("dirs", nargs="+", help="要扫描的目录")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--allow", action="append", default=[],
                    help="显式白名单（整套路径），只用于确认过可分发的情况")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    results = [scan(d, set(args.allow)) for d in args.dirs if os.path.isdir(d)]
    missing = [d for d in args.dirs if not os.path.isdir(d)]

    if args.json:
        print(json.dumps({"results": results, "missing": missing},
                         ensure_ascii=False, indent=2))
        return 0 if all(r["ok"] for r in results) else 1

    total_fail = 0
    for r in results:
        tag = "✓ PASS" if r["ok"] else "✗ FAIL"
        print(f"\n[{tag}] {r['root']}")
        print(f"  扫描 {r['scanned']} 文件 | 自制模板 {r['templates']} 个 | "
              f"禁止项 {len(r['fails'])} | 提示 {len(r['warns'])}")
        for f in r["fails"]:
            print(f"  ✗ {f['path']}  ({f['bytes']//1024} KB) — {f['reason']}")
        if not args.quiet:
            for w in r["warns"][:10]:
                if w["kind"] == "vendor_mention":
                    print(f"  · 品牌字样 {w['name']} @ {w['path']}（文档引用正常，人工确认）")
                else:
                    print(f"  · 白名单放行 @ {w['path']}")
            for b in r["big_files"][:5]:
                print(f"  · 大文件 {b['mb']} MB @ {b['path']}")
        total_fail += len(r["fails"])

    if missing:
        print("\n  跳过不存在的目录: " + ", ".join(missing))

    print()
    if total_fail:
        print(f"  ✗ 共 {total_fail} 项禁止内容 —— 不允许发布")
        return 1
    print("  ✓ 合规检查通过（无第三方 CAD 素材）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
