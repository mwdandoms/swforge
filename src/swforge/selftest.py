# -*- coding: utf-8 -*-
"""实机自检 —— 用真实 SolidWorks 验证每一项承诺。

为什么要有这个
--------------
同类项目的用户报过这些 bug（都有 issue 编号）：

- 切了文档但没真正激活，后续操作作用到错误的零件上（andrewbartels1 #91）
- 导出时顺手打开装配，用完不关，跑几次内存爆（#101）
- 自动标注的回读数返回 0，其实尺寸已经建出来了（#100）
- API 查询报出根本不存在的成员，LLM 照着编（#195）
- 连不上就卡住，报错看不出怎么修（vespo92 #1）

swforge 声称这些都已经处理了。**声称不算数**，所以做成可执行的检查：
每一项都在真机上跑一遍，读出真实结果再判定。

这台机器上 PASS 才有意义 —— 换一台 SW 版本不同的机器，跑一次就知道
哪些还能用、哪些坏了。CI 跑不了实机，这个命令就是补那块空白。

用法
----
    swforge selftest              # 全部跑
    swforge selftest --only mate  # 只跑名称里含 mate 的
    swforge selftest --keep       # 保留产物便于查看
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import traceback

__all__ = ["run_selftest", "CHECKS", "Check"]


class Check:
    """一项检查。fn 返回 (ok, detail)；抛异常视为失败。"""

    def __init__(self, name: str, title: str, fn, why: str = ""):
        self.name = name
        self.title = title
        self.fn = fn
        self.why = why


def _q235_density():
    """取 Q235 标准密度。lookup 返回 (密度, 弹性模量, 泊松比, 标准)。"""
    from .gb_materials import lookup
    try:
        spec = lookup("Q235")
    except Exception:                                  # noqa: BLE001
        return None
    if isinstance(spec, dict):
        return spec.get("density")
    if isinstance(spec, (tuple, list)) and spec:
        return spec[0]
    return None


def _close_created(work: str, prefix: str = ""):
    """关掉工作目录里属于本次自检的文档，释放 SW 文档名额。

    自检工具自己把名额占满、导致后续检查失败，是很容易犯的错。
    """
    from .session import get_session, _value
    try:
        sw = get_session().sw()
    except Exception:                                  # noqa: BLE001
        return
    try:
        docs = _value(sw, "GetDocuments") or []
    except Exception:                                  # noqa: BLE001
        return
    for d in docs:
        try:
            path = str(_value(d, "GetPathName") or "")
        except Exception:                              # noqa: BLE001
            continue
        if not path:
            continue
        in_work = os.path.abspath(path).lower().startswith(os.path.abspath(work).lower())
        if in_work and (not prefix or prefix.lower() in os.path.basename(path).lower()):
            try:
                sw.CloseDoc(path)
            except Exception:                          # noqa: BLE001
                pass


# ---------------------------------------------------------------- 检查项
def _chk_connect(work: str):
    """连接 + 版本。这是所有其他检查的前提。"""
    from .session import get_session
    r = get_session().ping()
    if not r.get("ok"):
        return False, f"连不上：{r.get('error')}"
    detail = f"SolidWorks {r.get('sw_version') or '?'}"
    ms = r.get("roundtrip_ms")
    if ms is not None:
        detail += f"，往返 {ms:.0f} ms"
    return True, detail


def _chk_activate(work: str):
    """文档切换后必须真正激活。

    对应 andrewbartels1 #91：切了文档但没激活，后续操作作用到错的零件上。
    做法：连续建两个零件，来回切三次，每次都回读 ActiveDoc 的标题。
    """
    from .session import get_session, _value
    from .modeling import PartBuilder

    sw = get_session().sw()
    a = os.path.join(work, "st_act_a.SLDPRT")
    b = os.path.join(work, "st_act_b.SLDPRT")
    for p in (a, b):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass

    pa = PartBuilder(a, material="Q235")
    pa.box("a", 0, 20, 0, 10, 0, 10)
    ra = pa.build(paint=False, keep_open=True)
    pb = PartBuilder(b, material="Q235")
    pb.box("b", 0, 30, 0, 10, 0, 10)
    rb = pb.build(paint=False, keep_open=True)
    if not (ra.ok and rb.ok):
        return False, f"建模失败 a={ra.ok} b={rb.ok}"

    bad = []
    for target, tag in ((a, "a"), (b, "b"), (a, "a")):
        sw.ActivateDoc(target)
        title = str(_value(sw.ActiveDoc, "GetTitle") or "")
        expect = os.path.splitext(os.path.basename(target))[0]
        # 关键：ActivateDoc 没报错不等于切过去了，必须回读标题确认。
        # 注意 GetTitle 返回的是不带扩展名的文档名。
        if expect.lower() not in title.lower():
            bad.append(f"切到 {tag} 后活动文档是 {title!r}")
    if bad:
        return False, "；".join(bad)
    return True, "3 次切换全部正确（每次都回读标题）"


def _chk_resource_guard(work: str):
    """文档数不能超上限，且清扫能真的收回来。

    对应 andrewbartels1 #101：用完不关，跑几次就爆。
    """
    from .resources import resource_status, sweep_documents
    from .modeling import PartBuilder

    before = resource_status()
    for i in range(3):
        p = os.path.join(work, f"st_res_{i}.SLDPRT")
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
        b = PartBuilder(p, material="Q235")
        b.box("b", 0, 10 + i, 0, 5, 0, 5)
        b.build(paint=False, keep_open=True)

    peak = resource_status()
    sweep_documents(dry_run=False)
    after = resource_status()
    detail = (f"峰值 {peak['document_count']}/{peak['limit']}，"
              f"清扫后 {after['document_count']}")

    # 这一项会故意建几个文档出来，跑完必须自己收拾干净，
    # 否则后面的检查会因为名额不足而连环失败（自检工具自己制造问题）。
    _close_created(work, "st_res_")

    if peak["document_count"] > peak["limit"]:
        return False, f"超上限：{detail}"
    if after["document_count"] > before["document_count"]:
        return False, f"清扫没收回：{detail}"
    return True, detail


def _chk_readback(work: str):
    """建完必须能回读到真实几何。

    对应 andrewbartels1 #100：回读数返回 0，其实已经建出来了。
    这里用可手算的体积做断言：100×20×50 = 100000 mm³。
    """
    from .modeling import PartBuilder

    p = os.path.join(work, "st_rb.SLDPRT")
    if os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass
    b = PartBuilder(p, material="Q235")
    b.box("底板", 0, 100, 0, 20, 0, 50)
    r = b.build(paint=False, keep_open=False)
    if not r.ok:
        return False, f"建模失败：{r.error}"

    vol = r.volume_mm3
    if not vol:
        return False, "回读体积为 0 —— 这正是同类项目的典型失败"
    expect = 100 * 20 * 50
    err = abs(vol - expect) / expect
    detail = f"体积 {vol:.1f} mm³（理论 {expect}），偏差 {err * 100:.3f}%"
    if err > 0.001:
        return False, detail
    return True, detail


def _chk_material(work: str):
    """材质必须真的赋上 —— 密度不能是 1000（水）。

    这是本项目发现的坑：SolidWorks 默认密度 1000，没赋材质时质量错 7.85 倍。
    用 mass/volume 反算密度，这是最硬的证据。
    """
    from .modeling import PartBuilder

    p = os.path.join(work, "st_mat.SLDPRT")
    if os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass
    b = PartBuilder(p, material="Q235")
    b.box("b", 0, 50, 0, 10, 0, 10)
    r = b.build(paint=False, keep_open=False)
    if not r.ok:
        return False, f"建模失败：{r.error}"

    applied = (r.material_applied or "").strip()
    if not applied:
        return False, "SolidWorks 回读不到材质名，赋值没生效（会退回水密度）"
    if not r.volume_mm3 or r.volume_mm3 <= 0:
        return False, f"材质={applied}，但体积回读为 {r.volume_mm3}"

    dens = r.mass_kg / (r.volume_mm3 * 1e-9)          # kg / m3
    want = _q235_density()
    detail = f"材质回读={applied}，密度反算 {dens:.0f} kg/m³"
    if abs(dens - 1000.0) < 2.0:
        return False, detail + "（等于水的密度，材质没真赋上）"
    if want and abs(dens - float(want)) > 5.0:
        return False, detail + f"，Q235 应为 {want}"
    return True, detail + (f"（Q235 标准 {want:.0f}）" if want else "")


def _chk_interference(work: str):
    """两个已知重叠的零件，干涉体积必须精确算出来。

    为什么用装配：同一零件里互相重叠的实体，SolidWorks 会合并成一个体，
    根本不存在干涉对。必须两个独立零件装在一起。
    """
    from .modeling import PartBuilder
    from .assembly import AssemblyBuilder, check_interference

    parts = []
    for name in ("st_ia", "st_ib"):
        p = os.path.join(work, f"{name}.SLDPRT")
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
        b = PartBuilder(p, material="Q235")
        b.box("b", 0, 20, 0, 20, 0, 20)                # 每个零件 20 立方
        b.build(paint=False, keep_open=False)
        parts.append(p)

    asm = os.path.join(work, "st_intf.SLDASM")
    if os.path.isfile(asm):
        try:
            os.remove(asm)
        except OSError:
            pass
    ab = AssemblyBuilder(asm)
    ab.add(parts[0], x=0, y=0, z=0, fixed=True)
    ab.add(parts[1], x=10, y=0, z=0)                   # 沿 X 偏移 10 → 重叠 10mm
    r = ab.build()
    if not r.get("ok"):
        return False, f"装配失败：{r.get('error')}"

    res = check_interference(asm)
    if not res.get("ok"):
        return False, f"干涉检查失败：{res.get('error')}"

    count = res.get("interference_count")
    rows = res.get("interferences") or []
    # 判定标准：检查器必须真的报告出干涉，而且数量对得上
    if not count:
        return False, f"干涉检查返回 {count} 处 —— 两个明显重叠的零件应至少有 1 处"
    if not rows:
        # 已知问题：count>0 但明细列表为空，调用方拿不到具体是哪两个零件
        return False, (f"报告 {count} 处干涉，但明细列表为空 —— "
                       f"调用方无法知道是哪两个零件相交")

    detail = f"报告 {count} 处干涉，明细 {len(rows)} 条"
    first = rows[0] if isinstance(rows[0], dict) else {}
    if first.get("volume_mm3") is not None:
        vol = float(first["volume_mm3"])
        expect = 10 * 20 * 20                          # 重叠 10×20×20 = 4000
        err = abs(vol - expect) / expect
        detail += f"，体积 {vol:.1f} mm³（理论 {expect}），偏差 {err*100:.2f}%"
        if err > 0.02:
            return False, detail
    return True, detail


def _chk_mate(work: str):
    """配合必须真的加上 —— 用配合明细回读判断，不看返回值。"""
    from .modeling import PartBuilder
    from .assembly import AssemblyBuilder
    from .mates import MateBuilder

    parts = []
    for name in ("st_ma", "st_mb"):
        p = os.path.join(work, f"{name}.SLDPRT")
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
        b = PartBuilder(p, material="Q235")
        b.box("b", 0, 20, 0, 20, 0, 20)
        b.build(paint=False, keep_open=False)
        parts.append(p)

    asm = os.path.join(work, "st_mate.SLDASM")
    if os.path.isfile(asm):
        try:
            os.remove(asm)
        except OSError:
            pass
    ab = AssemblyBuilder(asm)
    ab.add(parts[0], x=0, y=0, z=0, fixed=True)
    ab.add(parts[1], x=60, y=0, z=0)
    r = ab.build()
    if not r.get("ok"):
        return False, f"装配失败：{r.get('error')}"

    # 判定方式：比配合前后组件的包围盒中心。配合真的生效，位置一定会变。
    before = MateBuilder(asm).apply()
    if not before.get("ok"):
        return False, f"读装配状态失败：{before.get('error')}"
    xb = [round(float(c["x"]), 3) for c in (before.get("component_boxes_center_mm") or [])]

    res = MateBuilder(asm).coincident(0, 1).apply()
    if not res.get("ok"):
        return False, f"配合失败：{res.get('error')}"
    xa = [round(float(c["x"]), 3) for c in (res.get("component_boxes_center_mm") or [])]

    mates = res.get("mates") or []
    detail = f"配合前 X={xb} 配合后 X={xa}，配合表 {len(mates)} 条"
    # 两个 20 立方在 x=0 和 x=60，重合配合会把它们拉到一起
    if xb == xa:
        return False, detail + " —— 位置没变，配合没生效"
    return True, detail


def _chk_drawing(work: str):
    """出图 + 尺寸值必须与模型一致（不是 0，也不是选错轴的值）。"""
    from .modeling import PartBuilder
    from .drawing import produce, add_dimensions

    # 前面几步会反复开关文档，连接可能失效，这一步开始前确认一次
    from .session import get_session
    if not get_session().ping().get("ok"):
        return False, "SolidWorks 连接已失效，无法出图"

    p = os.path.join(work, "st_dw.SLDPRT")
    d = os.path.join(work, "st_dw.SLDDRW")
    for f in (p, d):
        if os.path.isfile(f):
            try:
                os.remove(f)
            except OSError:
                pass
    b = PartBuilder(p, material="Q235")
    b.box("底板", 0, 160, 0, 20, 0, 100)
    r = b.build(paint=False, keep_open=False)
    if not r.ok:
        return False, f"建模失败：{r.error}"

    rp = produce(p, d, paper="A3", keep_open=True)
    if not rp.get("ok"):
        return False, f"出图失败：{rp.get('error')}"

    rd = add_dimensions(d, curated=True, internal=1)
    total = rd.get("after", 0)
    vals = []
    for x in ((rd.get("overall") or {}).get("dims") or []):
        v = x.get("value")
        if v:
            vals.append(float(v))
    detail = f"{total} 个尺寸，取值 {sorted(set(vals))}"
    if total < 4:
        return False, detail + " —— 尺寸太少，出图没生效"
    if not vals or all(v == 0 for v in vals):
        return False, detail + " —— 尺寸值为 0"
    if not any(abs(v - 160) < 0.5 for v in vals):
        return False, detail + " —— 没标出总长 160，可能选错了轴"
    return True, detail


def _chk_probe(work: str):
    """API 反射探测必须给出真实、可操作的明细。

    对应 andrewbartels1 #195：API 查询报出不存在的成员，LLM 照着编。
    """
    from .probe import probe_api

    r = probe_api()
    total = r.get("total_count") or 0
    avail = r.get("available_count") or 0
    apis = r.get("apis") or {}
    detail = (f"探测 {total} 项，可用 {avail} 项，"
              f"耗时 {r.get('elapsed_s', 0):.2f}s，"
              f"互操作 {r.get('assembly_version')}")
    if total <= 0:
        return False, detail + " —— 没有探测到任何 API"
    if avail <= 0:
        return False, detail + " —— 一项都不可用，反射路径有问题"
    if apis:
        sample = next(iter(apis.values()))
        if not isinstance(sample, dict):
            return False, detail + " —— apis 没有逐项明细，Agent 拿不到可操作信息"
    return True, detail


def _chk_concurrency(work: str):
    """模拟「另一个客户端把活动文档切走」，验证守卫能发现并抢回来。

    对应 hjbaard #10：几个 agent 同时连一个 SolidWorks 时，
    任一方的 ActivateDoc 都会把对方的活动文档切走。
    后果很隐蔽 —— 拉伸做在了错的零件上，而且没有报错。

    真正的多进程并发难以在单测里稳定复现，所以这里模拟它的**效果**：
    激活 A → 切到 B（相当于别人抢了）→ 检查守卫能不能发现 → 能不能抢回来。
    """
    from .modeling import PartBuilder
    from .guard import activate_verified, verify_active, active_title

    a = os.path.join(work, "st_cc_a.SLDPRT")
    b = os.path.join(work, "st_cc_b.SLDPRT")
    for p, w in ((a, 20), (b, 30)):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
        bd = PartBuilder(p, material="Q235")
        bd.box("b", 0, w, 0, 10, 0, 10)
        bd.build(paint=False, keep_open=True)

    # 1) 正常激活 A
    if not activate_verified(a):
        return False, "无法激活第一个文档"

    # 2) 模拟别的客户端抢走：切到 B
    from .session import get_session
    get_session().sw().ActivateDoc(b)
    stolen = active_title()

    # 3) 守卫必须发现 A 已经不是活动文档
    detected = not verify_active(a)
    if not detected:
        return False, (f"被切到 {stolen!r} 之后，verify_active(A) 仍然返回 True —— "
                       f"守卫失效，后续操作会静默作用到错的零件上")

    # 4) 守卫必须能把 A 抢回来
    restored = activate_verified(a, retries=3)
    if not restored:
        return False, "检测到被抢走了，但抢不回来"

    return True, (f"被切到 {stolen!r} 后正确检测到，并成功抢回；"
                  f"当前活动文档 {active_title()!r}")


CHECKS = [
    Check("connect", "连接与版本", _chk_connect,
          "同类项目最常见的第一道坎（vespo92 #1）"),
    Check("activate", "文档切换后真正激活", _chk_activate,
          "对应 andrewbartels1 #91"),
    Check("resource", "资源守卫与清扫", _chk_resource_guard,
          "对应 andrewbartels1 #101"),
    Check("readback", "几何回读准确", _chk_readback,
          "对应 andrewbartels1 #100"),
    Check("material", "材质真的赋上（密度≠1000）", _chk_material,
          "SolidWorks 默认密度是水，质量会错 7.85 倍"),
    Check("interference", "干涉体积精确", _chk_interference,
          "同类项目这次调用常返回 0/None"),
    Check("mate", "配合真正加成功", _chk_mate,
          "errStatus 语义反直觉，容易误判"),
    Check("drawing", "出图与尺寸值正确", _chk_drawing,
          "尺寸选错轴会标出错误的值"),
    Check("concurrency", "活动文档守卫（多客户端）", _chk_concurrency,
          "对应 hjbaard #10：多个客户端抢同一个 SolidWorks"),
    Check("probe", "API 反射探测", _chk_probe,
          "对应 andrewbartels1 #195"),
]


def run_selftest(work_dir: str | None = None,
                 only: str | None = None,
                 keep: bool = False,
                 progress=None) -> dict:
    """跑实机自检。

    参数
    ----
    work_dir  产物目录，默认建临时目录，跑完删掉
    only      只跑名称或标题里包含该字符串的检查
    keep      保留产物（不删临时目录）
    progress  回调 progress(result_dict)，用于实时打印

    返回 `{ok, passed, failed, skipped, results:[...], elapsed_s}`
    """
    import swforge
    from .session import get_session

    ping = get_session().ping()
    if not ping.get("ok"):
        return {
            "ok": False,
            "error": "连不上 SolidWorks，请先手动启动它。"
                     f"详情：{ping.get('error')}",
            "passed": 0, "failed": 0, "skipped": 0,
            "results": [], "elapsed_s": 0.0,
        }

    tmp_created = False
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="swforge_selftest_")
        tmp_created = True
    os.makedirs(work_dir, exist_ok=True)

    selected = CHECKS
    if only:
        low = only.lower()
        selected = [c for c in CHECKS
                    if low in c.name.lower() or low in c.title.lower()]

    results = []
    t0 = time.monotonic()
    for c in selected:
        ts = time.monotonic()
        try:
            try:
                ok, detail = c.fn(work_dir)
            except Exception as first_exc:             # noqa: BLE001
                # 连接被外部因素弄断（比如 SolidWorks 实例重启）时，
                # 一次重试往往就能过。重连不了就把原始错误抛上去。
                msg = str(first_exc)
                if "rot_failed" in msg or "Operation unavailable" in msg:
                    from .session import _SESSION_LOCAL
                    try:
                        import threading
                        import swforge.session as _sess
                        _sess._SESSION_LOCAL = threading.local()
                    except Exception:                  # noqa: BLE001
                        pass
                    ok, detail = c.fn(work_dir)
                else:
                    raise
        except Exception as exc:                       # noqa: BLE001
            ok = False
            detail = f"{type(exc).__name__}: {exc}"
            if os.environ.get("SWFORGE_SELFTEST_TRACE"):
                detail += "\n" + traceback.format_exc()
        one = {
            "name": c.name,
            "title": c.title,
            "why": c.why,
            "ok": bool(ok),
            "detail": detail,
            "elapsed_s": round(time.monotonic() - ts, 2),
        }
        results.append(one)
        if progress:
            progress(one)
        # 每项跑完清一次场：任何一项留下没关的文档都会挤占后续的名额
        _close_created(work_dir)

    try:
        from .resources import sweep_documents
        sweep_documents(dry_run=False)
    except Exception:                                  # noqa: BLE001
        pass

    if tmp_created and not keep:
        shutil.rmtree(work_dir, ignore_errors=True)

    passed = sum(1 for r in results if r["ok"])
    failed = len(results) - passed
    return {
        "ok": failed == 0 and bool(results),
        "passed": passed,
        "failed": failed,
        "skipped": len(CHECKS) - len(selected),
        "work_dir": None if (tmp_created and not keep) else work_dir,
        "swforge": getattr(swforge, "__version__", "?"),
        "sw_version": ping.get("sw_version"),
        "results": results,
        "elapsed_s": round(time.monotonic() - t0, 2),
    }
