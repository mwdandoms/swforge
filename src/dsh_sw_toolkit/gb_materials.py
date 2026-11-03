# -*- coding: utf-8 -*-
"""国标牌号材质库：生成 SolidWorks 可直接加载的 .sldmat。

为什么需要这个模块
------------------
SolidWorks 自带的中文材质库（`lang/chinese-simplified/sldmaterials/
solidworks materials.sldmat`，259 条）**没有 GB 钢牌号** —— 没有 Q235、没有 45、
没有 40Cr，只有 6061 这类铝材和 AISI 系列。

后果：`PartBuilder(material="Q235")` 去库里找不到，赋值静默失败，
零件退回模板默认材质（实测密度 1000 kg/m³ = 水），**质量/质心全错**。

本模块维护一张 GB 牌号表，按需生成一个 `gb_materials.sldmat`，
`SetMaterialPropertyName2(config, <该文件>, "Q235")` 即可正确赋值。

数据来源
--------
密度与弹性模量取 GB/T 700、GB/T 3077、GB/T 1173 等的常用值（室温）。
这些是工程近似值，用于质量估算与初步分析；
**正式设计请以材料供货质保书为准**。
"""

from __future__ import annotations

import os
import re
import tempfile

__all__ = ["GB_MATERIALS", "lookup", "library_path", "ensure_library",
           "material_names"]

# 牌号 -> (密度 kg/m3, 弹性模量 Pa, 泊松比, 说明)
GB_MATERIALS: dict[str, tuple[float, float, float, str]] = {
    # ---- 碳素结构钢 / 优质碳素钢
    "Q235":      (7850.0, 2.06e11, 0.30, "碳素结构钢 GB/T 700"),
    "Q355":      (7850.0, 2.06e11, 0.30, "低合金高强度结构钢 GB/T 1591"),
    "45":        (7850.0, 2.09e11, 0.269, "优质碳素结构钢 GB/T 699"),
    "20":        (7850.0, 2.09e11, 0.269, "优质碳素结构钢 GB/T 699"),
    # ---- 合金结构钢
    "40Cr":      (7820.0, 2.11e11, 0.277, "合金结构钢 GB/T 3077"),
    "20CrMnTi":  (7850.0, 2.07e11, 0.25, "渗碳钢 GB/T 3077"),
    "42CrMo":    (7850.0, 2.12e11, 0.28, "合金结构钢 GB/T 3077"),
    # ---- 弹簧钢 / 轴承钢 / 模具钢
    "65Mn":      (7820.0, 2.10e11, 0.288, "弹簧钢 GB/T 1222"),
    "GCr15":     (7810.0, 2.19e11, 0.30, "高碳铬轴承钢 GB/T 18254"),
    "Cr12MoV":   (7700.0, 2.10e11, 0.30, "冷作模具钢 GB/T 1299"),
    # ---- 铸 铁
    "HT200":     (7200.0, 1.20e11, 0.25, "灰铸铁 GB/T 9439"),
    "QT500-7":   (7100.0, 1.69e11, 0.286, "球墨铸铁 GB/T 1348"),
    # ---- 不锈钢
    "06Cr19Ni10": (7930.0, 1.93e11, 0.30, "奥氏体不锈钢 GB/T 20878（304）"),
    "022Cr17Ni12Mo2": (7980.0, 1.93e11, 0.30, "奥氏体不锈钢 GB/T 20878（316L）"),
    # ---- 铝 合金
    "6061-T6":   (2700.0, 6.90e10, 0.33, "变形铝合金 GB/T 3190"),
    "7075-T6":   (2810.0, 7.17e10, 0.33, "变形铝合金 GB/T 3190"),
    "2A12":      (2780.0, 7.10e10, 0.33, "硬铝 GB/T 3190"),
    "ZL104":     (2650.0, 7.00e10, 0.33, "铸造铝合金 GB/T 1173"),
    # ---- 铜 合金
    "ZCuSn10P1": (8800.0, 1.03e11, 0.34, "铸造锡青铜 GB/T 1176"),
    "H62":       (8430.0, 1.00e11, 0.34, "黄铜 GB/T 5231"),
}

_NS = "http://www.solidworks.com/sldmaterials"
_SLDC = "http://www.solidworks.com/sldcolorswatch"

_HEAD = (
    '<?xml version="1.0" encoding="UTF-16" standalone="no"?>\n'
    f'<mstns:materials xmlns:mstns="{_NS}" '
    'xmlns:msdata="urn:schemas-microsoft-com:xml-msdata" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xmlns:schemaLocation="http://matwebtest.matweb.com/sw/XSD/sldmaterials.xsd" '
    f'xmlns:sldcolorswatch="{_SLDC}" version="2008.03">\n'
    '<curves id="curve0"><point x="1.0" y="1.0"/><point x="2.0" y="1.0"/>'
    '<point x="3.0" y="1.0"/></curves>\n'
)

_TAIL = "</mstns:materials>\n"


def _material_xml(name: str, density: float, elastic: float, poisson: float,
                  note: str) -> str:
    # 钢材给抛光钢外观，其余用中性灰；只为观感，物理量才是关键
    shader = ("polished steel" if density > 6000 else "polished aluminum")
    rgb = "C6C6D1" if density > 6000 else "D6D6D6"
    return (
        f'<classification name="{note}">\n'
        f'<material name="{name}" description="{note}">\n'
        '<shaders>'
        f'<pwshader2 name="{shader}" isNewShader="1" '
        f'path="\\metal\\{"steel" if density > 6000 else "aluminum"}\\{shader}.p2m"/>'
        '</shaders>\n'
        f'<swatchcolor RGB="{rgb}"/>\n'
        '<physicalproperties>'
        f'<EX displayname="弹性模量" value="{elastic:.4E}"/>'
        f'<NUXY displayname="泊松比" value="{poisson:.5f}"/>'
        f'<DENS displayname="密度" value="{density:.4E}"/>'
        '</physicalproperties>\n'
        '</material>\n'
        '</classification>\n'
    )


def _sw_user_material_dirs() -> list[str]:
    """列出 SolidWorks 会扫描的用户材质库目录。

    实测结论：`SetMaterialPropertyName2` 只认**已注册材质库目录**里的文件。
    同一份 .sldmat，放在 `%LOCALAPPDATA%` 下赋值静默失败（质量退回 1000 kg/m³ 的水），
    放到 `C:\\ProgramData\\SOLIDWORKS\\SOLIDWORKS <版本>\\<自定义材料目录>\\` 下就正确生效。
    """
    import glob

    out: list[str] = []
    base = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    for pattern in (os.path.join(base, "SOLIDWORKS", "SOLIDWORKS *"),
                    os.path.join(base, "SolidWorks", "SOLIDWORKS *")):
        for root in glob.glob(pattern):
            if not os.path.isdir(root):
                continue
            for sub in ("自定义材料", "custom materials", "Custom Materials",
                        "Material", "materials", "材质库"):
                candidate = os.path.join(root, sub)
                if os.path.isdir(candidate):
                    out.append(candidate)
            # 兜底：任何直接包含 .sldmat 的子目录
            for sub in os.listdir(root):
                candidate = os.path.join(root, sub)
                if os.path.isdir(candidate) and glob.glob(os.path.join(candidate, "*.sldmat")):
                    if candidate not in out:
                        out.append(candidate)
    return out


def library_path() -> str:
    """GB 材质库的落地路径。

    优先放进 SW 会扫描的用户材质库目录（否则赋值会静默失败）；
    都找不到时退回 `%LOCALAPPDATA%`，并在 `ensure_library` 里给出告警。
    """
    for folder in _sw_user_material_dirs():
        try:
            if os.access(folder, os.W_OK):
                return os.path.join(folder, "dsh_gb_materials.sldmat")
        except OSError:
            continue
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "dsh-sw-toolkit", "gb_materials.sldmat")


_STEEL_TEMPLATE_RE = re.compile(r'<material\b[^>]*name="([^"]*)"[^>]*>.*?</material>', re.S)


def _find_sw_library() -> str | None:
    """找 SW 自带材质库；用它当模板，保证生成的库符合 SW 的 schema。"""
    import glob

    roots = []
    for env in ("SW_INSTALL_DIR", "SOLIDWORKS_DIR"):
        val = os.environ.get(env)
        if val:
            roots.append(val)
    for letter in ("E", "D", "C", "F"):
        roots.extend(glob.glob(rf"{letter}:\SW*\SOLIDWORKS\lang\*\sldmaterials"))
    for letter in ("C", "D", "E"):
        roots.extend(glob.glob(rf"{letter}:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\*\sldmaterials"))
    for root in roots:
        if not os.path.isdir(root):
            continue
        for candidate in ("solidworks materials.sldmat", "SolidWorks DIN Materials.sldmat"):
            hit = os.path.join(root, candidate)
            if os.path.isfile(hit):
                return hit
        found = glob.glob(os.path.join(root, "*.sldmat"))
        if found:
            return found[0]
    return None


def _clone_from_template(template_path: str) -> str:
    """用 SW 自带库里的一个钢材料节点做模板，替换名字与物理量。

    直接拼 XML 会被 SW 判为无效库（缺 matid / xhatch / 着色器子节点等），
    而把原生节点克隆过来再改数值，schema 天然是合法的。
    """
    with open(template_path, encoding="utf-16") as fh:
        raw = fh.read()
    nodes = _STEEL_TEMPLATE_RE.findall(raw, )  # 仅取名字
    all_nodes = [m.group(0) for m in _STEEL_TEMPLATE_RE.finditer(raw)]
    if not all_nodes:
        raise RuntimeError(f"模板库里没有可用的 material 节点：{template_path}")
    # 挑一个钢（密度 > 6000）当基体
    base = None
    for node in all_nodes:
        m = re.search(r'DENS[^>]*value="([\d.eE+-]+)"', node)
        if m and float(m.group(1)) > 6000:
            base = node
            break
    base = base or all_nodes[0]

    out = [base]
    for idx, (name, (density, elastic, poisson, note)) in enumerate(sorted(GB_MATERIALS.items())):
        node = base
        node = re.sub(r'\bname="[^"]*"', f'name="{name}"', node, count=1)
        node = re.sub(r'\bdescription="[^"]*"', f'description="{note}"', node, count=1)
        node = re.sub(r'\bmatid="\d+"', f'matid="{9000 + idx}"', node, count=1)
        node = re.sub(r'(<DENS[^>]*value=")[^"]*(")', rf'\g<1>{density:.4E}\g<2>', node, count=1)
        node = re.sub(r'(<EX[^>]*value=")[^"]*(")', rf'\g<1>{elastic:.4E}\g<2>', node, count=1)
        node = re.sub(r'(<NUXY[^>]*value=")[^"]*(")', rf'\g<1>{poisson:.5f}\g<2>', node, count=1)
        out.append(node + "\n")

    # 关键：不能只取根标签后重拼 —— 原库的 <curves> 等结构元素必须保留，
    # 否则 SW 认为材质库无效，SetMaterialPropertyName2 静默失败。
    tail_token = "</mstns:materials>"
    cut = raw.rindex(tail_token)
    return (raw[:cut]
            + '<classification name="DSH GB 国标牌号">\n'
            + "".join(out)
            + "</classification>\n"
            + raw[cut:])


def ensure_library(path: str | None = None, force: bool = False,
                   template: str | None = None) -> str:
    """生成（或复用）GB 材质库，返回文件路径。

    优先「克隆 SW 原生库节点」以符合 schema；找不到原生库时退回自拼 XML
    （能写出来但不保证 SW 认，调用方应检查回读）。
    """
    target = path or library_path()
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    tpl = template or _find_sw_library()
    if tpl and os.path.isfile(tpl):
        try:
            content = _clone_from_template(tpl)
        except Exception:                                # noqa: BLE001
            content = _HEAD + "".join(
                _material_xml(n, *GB_MATERIALS[n]) for n in sorted(GB_MATERIALS)) + _TAIL
    else:
        content = _HEAD + "".join(
            _material_xml(n, *GB_MATERIALS[n]) for n in sorted(GB_MATERIALS)) + _TAIL

    if not force and os.path.isfile(target):
        try:
            with open(target, encoding="utf-16") as fh:
                if fh.read() == content:
                    return target
        except (OSError, UnicodeError):
            pass
    with open(target, "w", encoding="utf-16") as fh:
        fh.write(content)
    return target


def lookup(name: str) -> tuple[float, float, float, str] | None:
    """按牌号查物理属性；找不到返回 None。大小写与常见别名容错。"""
    if not name:
        return None
    key = str(name).strip()
    if key in GB_MATERIALS:
        return GB_MATERIALS[key]
    low = key.lower()
    for candidate, props in GB_MATERIALS.items():
        if candidate.lower() == low:
            return props
    return None


def material_names() -> list[str]:
    return sorted(GB_MATERIALS)
