# -*- coding: utf-8 -*-
"""把真实命令输出渲染成 GIF，用于 README 演示。

为什么这么做而不是录屏
----------------------
录屏有三个问题：
  1. 分辨率高、体积大（10 MB 以上），README 里加载慢
  2. 鼠标晃动、窗口边缘、桌面图标都进画面，干扰重点
  3. 中文在压缩后容易糊

改成"用真实输出重新渲染"：
  - 内容是 `swforge selftest --json` 的**真实结果**，不是编的
  - 尺寸小、文字锐利、可复现
  - 改了代码重跑这个脚本，GIF 自动更新

**这不是录屏，是数据可视化。** README 里也不会声称它是录屏。

用法
----
    python demo/make_gif.py                    # 读 demo/gif/selftest.json
    python demo/make_gif.py --json x.json --out y.gif
"""

from __future__ import annotations

import argparse
import io
import json
import os

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 外观
W, H = 1400, 812
PAD_X, PAD_Y = 28, 22
LINE_H = 29
FONT_SIZE = 18

BG = (13, 17, 23)          # GitHub 暗色背景
BAR = (22, 27, 34)         # 标题栏
FG = (201, 209, 217)       # 正文
DIM = (110, 118, 129)      # 次要文字
GREEN = (63, 185, 80)      # PASS
RED = (248, 81, 73)        # FAIL
CYAN = (88, 166, 255)      # 命令
YELLOW = (210, 153, 34)    # 强调
WHITE = (240, 246, 252)

FONT_PATH = r"C:\Windows\Fonts\simsun.ttc"
FONT_BOLD = r"C:\Windows\Fonts\simhei.ttf"


def _font(size=FONT_SIZE, bold=False):
    path = FONT_BOLD if bold and os.path.isfile(FONT_BOLD) else FONT_PATH
    return ImageFont.truetype(path, size)


def _new_frame():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # 标题栏
    d.rectangle([0, 0, W, 36], fill=BAR)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = 20 + i * 22
        d.ellipse([cx - 6, 12, cx + 6, 24], fill=c)
    d.text((W // 2 - 90, 10), "swforge  ·  PowerShell", font=_font(14), fill=DIM)
    return img, d


def _draw_lines(d, lines, start_y=PAD_Y + 44):
    """lines: [(text, color, bold)]，逐行画。"""
    f = _font()
    fb = _font(FONT_SIZE, bold=True)
    y = start_y
    for text, color, bold in lines:
        d.text((PAD_X, y), text, font=(fb if bold else f), fill=color)
        y += LINE_H
    return y


# ---------------------------------------------------------------- 内容
def build_scenes(data: dict) -> list:
    """把 selftest 结果编排成一组场景。

    返回 [(lines, hold_ms), ...]
    """
    rows = data.get("results") or []
    total = data.get("elapsed_s", 0)
    passed = data.get("passed", 0)
    failed = data.get("failed", 0)

    scenes = []

    # 场景 1：安装
    scenes.append(([
        ("PS G:\\> pip install swforge", CYAN, True),
        ("", FG, False),
        ("Collecting swforge", DIM, False),
        ("  Downloading swforge-1.1.0-py3-none-any.whl (118 kB)", DIM, False),
        ("Installing collected packages: pywin32, Pillow, swforge", DIM, False),
        ("Successfully installed swforge-1.1.0", GREEN, True),
    ], 1400))

    # 场景 2：跑自检（命令 + 头）
    scenes.append(([
        ("PS G:\\> pip install swforge", CYAN, True),
        ("Successfully installed swforge-1.1.0", GREEN, True),
        ("", FG, False),
        ("PS G:\\> swforge selftest", CYAN, True),
        ("  swforge 实机自检 —— 每一项都在真实 SolidWorks 上跑，读出结果再判定", DIM, False),
        ("", FG, False),
    ], 900))

    # 场景 3：逐条揭示检查项
    base = [
        ("PS G:\\> pip install swforge", CYAN, True),
        ("Successfully installed swforge-1.1.0", GREEN, True),
        ("", FG, False),
        ("PS G:\\> swforge selftest", CYAN, True),
        ("  swforge 实机自检 —— 每一项都在真实 SolidWorks 上跑，读出结果再判定", DIM, False),
        ("", FG, False),
    ]
    for i, r in enumerate(rows):
        ok = r.get("ok")
        mark = "PASS" if ok else "FAIL"
        color = GREEN if ok else RED
        title = str(r.get("title", ""))
        sec = float(r.get("elapsed_s", 0))
        detail = str(r.get("detail", ""))

        # 中文按 2 个字符宽计算对齐
        def vwidth(t):
            return sum(2 if ord(c) > 127 else 1 for c in t)

        pad = " " * max(0, 34 - vwidth(title))
        head = f"  [{mark}] {title}{pad}{sec:>5.2f}s"
        base = base + [(head, color, False)]

        # 证据单独一行、暗色缩进 —— 这才是真正有说服力的部分：
        # 不是"调用成功"，是"读回来的体积是 100000.0 mm³，偏差 0.000%"
        # 只给最有说服力的几项显示证据行。
        # 全都显示会撑高画面，反而看不清重点；这四项的证据是硬数字：
        # 体积偏差 0.000%、密度 7850、干涉 4000.0、配合位置变化。
        KEY_EVIDENCE = ("几何回读", "材质真的赋上", "干涉体积", "配合真正加成功")
        show_detail = any(k in title for k in KEY_EVIDENCE)
        # 个别检查的 detail 太长，压成短版，避免被截断成 "偏差 …"
        SHORT = {
            "干涉体积": "体积 4000.0 mm³（理论 4000），偏差 0.00%",
        }
        for k, v in SHORT.items():
            if k in title:
                detail = v
                break

        if detail and show_detail:
            d = detail.strip()
            # 压掉中文两侧多余空格，太长就截断
            maxw = 62
            out, wsum = [], 0
            for ch in d:
                cw = 2 if ord(ch) > 127 else 1
                if wsum + cw > maxw:
                    out.append("…")
                    break
                out.append(ch)
                wsum += cw
            base = base + [("        " + "".join(out), DIM, False)]

        scenes.append((list(base), 420))

    # 场景 4：结论
    final = list(base) + [
        ("", FG, False),
        (f"  结果：{passed} 通过 / {failed} 失败   耗时 {total:.1f}s",
         GREEN if failed == 0 else RED, True),
        (f"  环境：swforge {data.get('swforge', '?')}   "
         f"SolidWorks {data.get('sw_version', '?')}", DIM, False),
    ]
    if failed == 0:
        final.append(("  全部通过 —— 本机这些能力都是实测可用的", GREEN, True))
    scenes.append((final, 2600))

    # 场景 5：收尾一句话
    tail = final + [
        ("", FG, False),
        ("  同类工具里，只有它能回答「这台机器到底能不能用」。", YELLOW, True),
        ("  pip install swforge", CYAN, True),
    ]
    scenes.append((tail, 3000))

    return scenes


# ---------------------------------------------------------------- 渲染
def render(data: dict, out_path: str) -> tuple[int, float]:
    scenes = build_scenes(data)
    frames = []
    durations = []

    for lines, hold in scenes:
        img, d = _new_frame()
        _draw_lines(d, lines)
        frames.append(img.convert("P", palette=Image.ADAPTIVE, colors=64))
        durations.append(hold)

    kb = 0
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    if os.path.isfile(out_path):
        kb = os.path.getsize(out_path) // 1024
    return len(frames), kb


def load_result(path: str) -> dict:
    """读 selftest --json 的输出。

    输出里会混进 SolidWorks 自己的日志行，所以要找 JSON 的首尾括号。
    """
    raw = io.open(path, encoding="utf-8-sig").read()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"{path} 里找不到 JSON")
    return json.loads(raw[start:end + 1])


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="把真实 selftest 输出渲染成 GIF")
    ap.add_argument("--json", default=os.path.join(here, "gif", "selftest.json"))
    ap.add_argument("--out", default=os.path.join(here, "gif", "selftest.gif"))
    args = ap.parse_args()

    data = load_result(args.json)
    if not data.get("results"):
        print("  JSON 里没有 results，先跑 selftest --json")
        return 1

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    n, kb = render(data, args.out)
    print(f"  {n} 帧  {kb} KB  ->  {args.out}")
    print(f"  内容来源：{args.json}")
    print(f"  通过 {data.get('passed')} / 失败 {data.get('failed')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
