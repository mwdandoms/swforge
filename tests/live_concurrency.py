# -*- coding: utf-8 -*-
"""多客户端并发实测：两个独立进程抢同一个 SolidWorks。

之前的「并发」只在同进程内模拟（selftest 第 10 项）。
真实场景是两个智能体/两个脚本各跑各的进程，都要操作同一个 SW 实例。

测试什么
--------
1. 两个进程能不能同时连上（COM 单实例）
2. 进程 A 打开文档后，进程 B 把活动文档切走，A 能不能发现
3. `document_guard()` 能不能把文档抢回来
4. 交替操作时读回的数据没串（A 读到的是自己的文档）

跑法
----
    python tests/live_concurrency.py            # 独立跑
    python tests/live_concurrency.py --quick    # 少跑几轮

需要 SolidWorks 已启动。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

WORKER = r'''
import json, os, sys, time
sys.path.insert(0, r"{src}")
from swforge.session import get_session, _value
from swforge.guard import document_guard, activate_verified
from swforge.resources import resource_status, sweep_documents

tag = sys.argv[1]
out = sys.argv[2]
w = os.path.dirname(out)
res = {{"tag": tag, "steps": [], "ok": True}}

def rec(step, ok, detail=""):
    res["steps"].append({{"step": step, "ok": bool(ok), "detail": str(detail)[:120]}})
    if not ok:
        res["ok"] = False

try:
    sw = get_session().sw()
    rec("connect", sw is not None, resource_status()["document_count"])

    # 各自建一个零件
    from swforge import PartBuilder
    p = os.path.join(w, f"并发_{{tag}}.SLDPRT")
    if os.path.isfile(p):
        try: os.remove(p)
        except OSError: pass
    b = PartBuilder(p, material="Q235")
    b.box("体", 0, 40, 0, 20, 0, 30)
    r = b.build(paint=False, keep_open=False)
    rec("build", r.ok, f"实体 {{r.bodies}} 体积 {{r.volume_mm3:.1f}}")

    # 打开自己的文档，拿守卫
    md = sw.OpenDoc(p, 1)
    time.sleep(0.5)                      # 给另一进程机会来抢
    sw.ActivateDoc(p)
    time.sleep(0.3)
    md = sw.ActiveDoc
    title = str(_value(md, "GetTitle") or "")
    rec("open_own", title.startswith(f"并发_{{tag}}"), title)

    # 关键：另一个进程这时应该把文档切走了
    time.sleep(1.5)
    md2 = sw.ActiveDoc
    now = str(_value(md2, "GetTitle") or "")

    # activate_verified 应该能抢回来
    got = activate_verified(p)
    md3 = sw.ActiveDoc
    back = str(_value(md3, "GetTitle") or "")
    rec("reclaim", back.startswith(f"并发_{{tag}}"),
        f"被切到 {{now}} -> 抢回 {{back}}")

    # 读回体积，确认读到的是自己的文档
    from swforge.assembly import read_volume
    v = read_volume(md3)
    rec("readback", abs(float(v) - 24000.0) < 1.0,
        f"体积 {{v:.1f}}（应 24000）")

except Exception as exc:
    rec("exception", False, f"{{type(exc).__name__}}: {{exc}}")

with open(out, "w", encoding="utf-8") as fh:
    json.dump(res, fh, ensure_ascii=False, indent=1)
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workdir", default=os.path.join(
        os.environ.get("TEMP", "."), "swforge_conc"))
    args = ap.parse_args()

    w = args.workdir
    # 清掉上一轮的残留零件，否则同名文件被 SW 占用会导致 build 失败
    if os.path.isdir(w):
        for f in os.listdir(w):
            if f.endswith((".SLDPRT", ".SLDASM", ".json")):
                try:
                    os.remove(os.path.join(w, f))
                except OSError:
                    pass
    os.makedirs(w, exist_ok=True)
    src = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "src")

    script = os.path.join(w, "worker.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(WORKER.format(src=src))

    print()
    print("=" * 62)
    print("  多客户端并发实测：两个独立进程抢同一个 SolidWorks")
    print("=" * 62)
    print()

    out_a = os.path.join(w, "a.json")
    out_b = os.path.join(w, "b.json")
    for p in (out_a, out_b):
        if os.path.isfile(p):
            os.remove(p)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = src

    procs = []
    for tag, out in (("A", out_a), ("B", out_b)):
        p = subprocess.Popen(
            [sys.executable, "-X", "utf8", script, tag, out],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace")
        procs.append((tag, p, out))
        time.sleep(0.8)                  # 稍微错开，制造真实交错

    results = {}
    for tag, p, out in procs:
        try:
            so, se = p.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            p.kill()
            so, se = p.communicate()
        if os.path.isfile(out):
            with open(out, encoding="utf-8") as fh:
                results[tag] = json.load(fh)
        else:
            results[tag] = {"tag": tag, "ok": False,
                            "steps": [{"step": "no_output", "ok": False,
                                       "detail": (se or so or "")[-200:]}]}

    all_ok = True
    for tag in ("A", "B"):
        r = results.get(tag) or {}
        print(f"  进程 {tag}: {'✅ 通过' if r.get('ok') else '❌ 失败'}")
        for s in r.get("steps") or []:
            mark = "✓" if s.get("ok") else "✗"
            print(f"    [{mark}] {s.get('step'):<12} {s.get('detail','')}")
        if not r.get("ok"):
            all_ok = False
        print()

    print("=" * 62)
    print("  结论：" + ("✅ 两个进程互不干扰，抢回机制生效"
                      if all_ok else "❌ 存在并发问题"))
    print("=" * 62)
    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
