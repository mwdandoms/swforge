# -*- coding: utf-8 -*-
"""GB 型材素材库索引 —— 让建模优先复用现成轮廓，而不是从零画。

═══════════════════════════════════════════════════════════════════════
为什么要有这个模块
═══════════════════════════════════════════════════════════════════════
用户本机装了 GB 型材焊件轮廓（位置自动探测，见 `_default_roots()`）。
以前 ``create_weldment_frame`` 每次都现场生成一个矩形环轮廓，
明明库里已经有 150×150×6.3 的方管，却还要重画一遍。

这个模块做两件事：
  1. **索引**：扫一遍素材库，把每个 ``.SLDLFP`` 的文件名解析成结构化参数
  2. **查表**：给定「方管 150×150×6.3」直接返回可用轮廓路径

拿到路径后交给 ``InsertStructuralWeldment5`` 即可，SW 会直接按原生
型材截面成型，不是拼板冒充。

命名不统一的现实
----------------
同一个库里混着好几种写法：
    方管      ``100 x 100 x 10.0``
    矩型管    ``100 x 50 x 3.2``
    圆管      ``10 x 1`` / ``102x1.5`` / ``102x3``
    冷弯空心方管 ``100×4``
    H型钢     ``HM150×100``
    热轧H型钢 ``HM148×100×6×9``
    等边角钢   ``10X10``
    工字钢    ``10`` / ``12.6``

所以解析按「分类 + 数字序列」来，不硬套统一格式；
匹配时按语义（边长/壁厚/直径）比较，数字顺序不对也能认出来。
"""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════════════
# 分类 → 规范类型
# ═══════════════════════════════════════════════════════════════════
CATEGORY_KIND = {
    "方管": "shs",
    "方通": "shs",
    "冷弯空心方管": "shs",
    "矩型管": "rhs",
    "矩形管": "rhs",
    "圆管": "chs",
    "无缝钢管": "chs",
    "等边角钢": "angle-eq",
    "不等边角钢": "angle-neq",
    "H型钢": "hbeam",
    "热轧H型钢": "hbeam",
    "工字钢": "ibeam",
    "槽钢": "channel",
    "轻型槽钢": "channel",
    "C型钢": "cchannel",
    "Z型钢": "zchannel",
    "圆钢": "round-bar",
    "方钢": "square-bar",
    "扁钢": "flat-bar",
    "六方钢": "hex-bar",
    "八角钢": "oct-bar",
    "铝型材": "alu",
    "起重机钢轨": "rail",
    "轻轨": "rail",
    "重轨": "rail",
    "U型折弯板": "u-bent",
}

#: 中文名（给用户看）
KIND_LABEL = {
    "shs": "方管", "rhs": "矩型管", "chs": "圆管",
    "angle-eq": "等边角钢", "angle-neq": "不等边角钢",
    "hbeam": "H型钢", "ibeam": "工字钢", "channel": "槽钢",
    "cchannel": "C型钢", "zchannel": "Z型钢",
    "round-bar": "圆钢", "square-bar": "方钢", "flat-bar": "扁钢",
    "hex-bar": "六方钢", "oct-bar": "八角钢", "alu": "铝型材",
    "rail": "钢轨", "u-bent": "U型折弯板",
}

#: 素材库目录可能的命名（客户机器上不一定是同一个名字）
LIBRARY_DIR_NAMES = ("sw基础材料库", "基础材料库", "GB型材库", "材料库", "型材库")


def _default_roots() -> list[str]:
    r"""自动探测素材库位置（1.6.1 有、1.7 起丢失，1.9.1 恢复）。

    按优先级：
      ① 环境变量 ``SWFORGE_LIBRARY`` / ``SWFORGE_MATERIAL_LIB``（``;`` 分隔多个）
      ② 用户目录下的常见命名
      ③ SolidWorks 自带的 GB 焊件轮廓目录（**按已装版本 glob，不写死年份**）
      ④ 各盘符根目录下的常见命名（只查一层，不深扫）

    ⚠️ 1.7.0 起这里退回成：写死某一个盘符下的素材库路径 + `SOLIDWORKS 2025`，
    客户机器上没有这两个路径就索引到 0 个轮廓，标准型材全部回退现场建模。
    """
    roots: list[str] = []

    # ① 环境变量优先
    for var in ("SWFORGE_LIBRARY", "SWFORGE_MATERIAL_LIB"):
        raw = os.environ.get(var)
        if raw:
            roots.extend(p.strip() for p in raw.split(os.pathsep) if p.strip())

    # ② 用户目录
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if home:
        roots.extend(os.path.join(home, n) for n in LIBRARY_DIR_NAMES)

    # ③ SolidWorks 自带焊件轮廓：扫 SOLIDWORKS * 版本目录，新版本优先
    base = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    for d in sorted(glob.glob(os.path.join(base, "SOLIDWORKS", "SOLIDWORKS *",
                                          "weldment profiles", "GB")), reverse=True):
        roots.append(d)
    roots.append(os.path.join(base, "SOLIDWORKS", "weldment profiles", "GB"))

    # ④ 各盘符根下的常见目录名（有界扫描，只查一层）
    for letter in "CDEFGH":
        for name in LIBRARY_DIR_NAMES:
            roots.append(f"{letter}:\\{name}")

    # 去重保序，只留真实存在的
    seen: set[str] = set()
    out: list[str] = []
    for r in roots:
        try:
            key = os.path.normcase(os.path.abspath(r))
        except Exception:                                       # noqa: BLE001
            continue
        if key in seen:
            continue
        seen.add(key)
        if os.path.isdir(r):
            out.append(r)
    return out


#: 默认搜索根目录（导入时探测一次，约几毫秒）
DEFAULT_ROOTS = _default_roots()

_NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers(name: str) -> list[float]:
    """从文件名里抽数字，忽略 × x X ✕ ＊ 等分隔符差异。"""
    return [float(x) for x in _NUM.findall(name)]


def _tag(name: str) -> str:
    """抽出型钢的型号前缀，比如 HM / HN / HW / QU。"""
    m = re.match(r"^\s*([A-Za-z]{1,3})", name)
    return m.group(1).upper() if m else ""


@dataclass
class Profile:
    """一条素材库记录。"""
    path: str
    category: str
    kind: str
    name: str
    numbers: list
    tag: str = ""
    source: str = ""

    @property
    def label(self) -> str:
        return f"{KIND_LABEL.get(self.kind, self.kind)} {self.name}"

    def as_dict(self) -> dict:
        return {"path": self.path, "category": self.category, "kind": self.kind,
                "name": self.name, "numbers": self.numbers, "tag": self.tag,
                "label": self.label, "source": self.source}


def _classify(category: str, name: str) -> dict:
    """把一条轮廓解析成 {a, b, t, d} 之类的语义参数。"""
    nums = _numbers(name)
    kind = CATEGORY_KIND.get(category, "")
    out = {"kind": kind, "tag": _tag(name), "numbers": nums}
    n = len(nums)

    if kind == "shs":
        # 方管：常见 "a x a x t" / "a x t" / "100×4"
        if n >= 3:
            out.update(a=max(nums[0], nums[1]), b=min(nums[0], nums[1]), t=nums[2])
        elif n == 2:
            # 冷弯空心方管的 "100×4" = 边长100、壁厚4
            big, small = max(nums), min(nums)
            out.update(a=big, b=big, t=small)
    elif kind == "rhs":
        if n >= 2:
            out.update(a=max(nums[0], nums[1]), b=min(nums[0], nums[1]),
                       t=nums[2] if n >= 3 else None)
    elif kind == "chs":
        if n >= 2:
            out.update(d=max(nums[0], nums[1]), t=min(nums[0], nums[1]))
        elif n == 1:
            out.update(d=nums[0], t=None)
    elif kind == "angle-eq":
        if n >= 2:
            out.update(a=max(nums[0], nums[1]), t=min(nums[0], nums[1]))
    elif kind == "angle-neq":
        if n >= 2:
            out.update(a=max(nums[0], nums[1]), b=min(nums[0], nums[1]),
                       t=nums[2] if n >= 3 else None)
    elif kind in ("hbeam", "ibeam", "channel", "cchannel", "zchannel"):
        if n >= 2:
            out.update(a=nums[0], b=nums[1],
                       t=nums[2] if n >= 3 else None,
                       tf=nums[3] if n >= 4 else None)
        elif n == 1:
            # 工字钢/槽钢的 "10" 是型号不是尺寸，保留 designation
            out.update(designation=nums[0])
    elif kind in ("round-bar", "square-bar", "hex-bar", "oct-bar"):
        if n:
            out.update(d=nums[0])
    elif kind == "flat-bar":
        if n >= 2:
            out.update(a=max(nums[0], nums[1]), b=min(nums[0], nums[1]))
    elif kind == "alu":
        if n >= 2:
            out.update(a=max(nums[0], nums[1]), b=min(nums[0], nums[1]))
    elif kind == "rail":
        if n:
            out.update(designation=nums[0])
    return out


class MaterialLibrary:
    """GB 型材素材库。

    用法
    ----
        lib = MaterialLibrary()
        lib.index()                                  # 扫一次，约 1-2 秒
        lib.find(kind="shs", a=150, b=150, t=6.3)    # 精确匹配
        lib.search("150")                            # 关键字
        lib.best(kind="rhs", a=150, b=100, t=6.0)    # 最接近的一个
    """

    def __init__(self, roots=None):
        self.roots = [r for r in (roots or DEFAULT_ROOTS) if os.path.isdir(r)]
        self._items: list[Profile] = []
        self._indexed = False
        self.scanned = 0

    # ------------------------------------------------------------ 索引
    def index(self, force: bool = False) -> dict:
        if self._indexed and not force:
            return {"ok": True, "count": len(self._items), "cached": True,
                    "roots": self.roots}
        items: list[Profile] = []
        for root in self.roots:
            for dirpath, _dirs, files in os.walk(root):
                for fn in files:
                    if not fn.lower().endswith(".sldlfp"):
                        continue
                    category = os.path.basename(dirpath)
                    if category.lower() in ("weldment profiles", "gb"):
                        category = category  # 平铺目录，用父名
                    stems = os.path.splitext(fn)[0]
                    info = _classify(category, stems)
                    items.append(Profile(
                        path=os.path.join(dirpath, fn),
                        category=category,
                        kind=info.get("kind") or "",
                        name=stems,
                        numbers=info.get("numbers") or [],
                        tag=info.get("tag") or "",
                        source=root,
                    ))
                    # 语义参数挂到 numbers 之外，用私有字段
                    items[-1].__dict__["parsed"] = info
        self._items = items
        self._indexed = True
        self.scanned = len(items)
        cats = {}
        for it in items:
            cats.setdefault(it.category, 0)
            cats[it.category] += 1
        return {"ok": bool(items), "count": len(items), "categories": cats,
                "roots": self.roots, "cached": False}

    # ------------------------------------------------------------ 查询
    def categories(self) -> dict:
        self.index()
        out = {}
        for it in self._items:
            out.setdefault(it.category, []).append(it)
        return {k: {"count": len(v), "kind": v[0].kind,
                    "label": KIND_LABEL.get(v[0].kind, v[0].kind)} for k, v in out.items()}

    def search(self, keyword: str, limit: int = 20) -> list[dict]:
        """按文件名关键字模糊查。"""
        self.index()
        kw = str(keyword).strip().lower()
        if not kw:
            return []
        hits = [it for it in self._items if kw in it.name.lower()]
        return [h.as_dict() for h in hits[:limit]]

    def find(self, kind=None, *, a=None, b=None, t=None, d=None,
             tag=None, tol=0.05, limit=20) -> list[dict]:
        """按语义参数精确查（带容差）。

        kind  shs / rhs / chs / angle-eq / hbeam ... 见 CATEGORY_KIND
        a,b   边长或高宽（mm）；方管 a=b=边长
        t     壁厚（mm）
        d     直径（mm），圆管/圆钢用
        tag   型号前缀，如 HM / HN
        """
        self.index()
        out = []
        for it in self._items:
            if kind and it.kind != kind:
                continue
            if tag and it.tag.upper() != str(tag).upper():
                continue
            p = it.__dict__.get("parsed") or {}

            def near(key, want):
                if want is None:
                    return True
                got = p.get(key)
                if got is None:
                    return False
                return abs(float(got) - float(want)) <= tol

            if not (near("a", a) and near("b", b) and near("t", t) and near("d", d)):
                continue
            out.append(it.as_dict())
        # 参数越接近越靠前
        return out[:limit]

    def best(self, kind=None, **kw) -> dict | None:
        """给一个最合适的；找不到返回 None。"""
        hits = self.find(kind, **kw)
        if not hits:
            return None
        return hits[0]

    def resolve_section(self, *, shape="shs", a=None, b=None, t=None, d=None,
                        allow_nearest=True) -> dict:
        """给建模用的一步到位接口：返回可交给 InsertStructuralWeldment5 的路径。

        返回 {ok, path, profile, exact, candidates, advice}
        """
        kind = {"shs": "shs", "rhs": "rhs", "chs": "chs",
                "方管": "shs", "矩型管": "rhs", "圆管": "chs"}.get(str(shape).lower(), shape)
        if kind == "shs":
            a = a if a is not None else b
            b = b if b is not None else a
        hits = self.find(kind, a=a, b=b, t=t, d=d)
        if hits:
            return {"ok": True, "path": hits[0]["path"], "profile": hits[0],
                    "exact": True, "candidates": hits[:5],
                    "advice": "素材库有同型号，直接用，不要从零建模"}
        if not allow_nearest:
            return {"ok": False, "path": None, "exact": False,
                    "candidates": [], "advice": "素材库没有该型号"}
        # 找最接近的：按语义参数算距离，壁厚权重高（壁厚选错比边长选错更致命）
        self.index()
        pool = [it for it in self._items if it.kind == kind]
        if not pool:
            return {"ok": False, "path": None, "exact": False, "candidates": [],
                    "advice": f"素材库没有 {KIND_LABEL.get(kind, kind)} 这一类"}

        def dist(it) -> float:
            p = it.__dict__.get("parsed") or {}
            d = 0.0
            for key, want, weight in (("a", a, 1.0), ("b", b, 1.0),
                                      ("t", t, 2.5), ("d", d, 1.0)):
                if want is None:
                    continue
                got = p.get(key)
                if got is None:
                    d += 50.0 * weight        # 缺参数：重罚
                else:
                    d += abs(float(got) - float(want)) * weight
            return d

        pool.sort(key=dist)
        near = [p.as_dict() for p in pool[:5]]
        want_desc = "/".join(str(x) for x in (a, b, t, d) if x is not None)
        return {"ok": False, "path": None, "exact": False, "candidates": near,
                "advice": (f"素材库没有 {KIND_LABEL.get(kind, kind)} {want_desc} 的完全一致型号；"
                           f"最接近的是 {near[0]['name'] if near else '无'}，"
                           "确认是否可用，否则回退到现场建模")}


def default_library() -> MaterialLibrary:
    lib = MaterialLibrary()
    lib.index()
    return lib
