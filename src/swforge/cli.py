"""命令行入口：`swforge <子命令>`"""
from __future__ import annotations
import argparse
import json
import os
import sys
_CJK_SAFE = ('utf-8', 'utf8', 'cp65001', 'cp936', 'gbk', 'gb2312', 'big5', 'cp950')

def _stream_encoding(stream) -> str:
    try:
        return (getattr(stream, 'encoding', '') or '').lower()
    except Exception:
        return ''

def _make_output_safe() -> None:
    """让 CLI 输出永远不会因为编码崩掉。

    两步：
    1. 把 stdout/stderr 的 errors 设成 replace —— 编不出来的字符变 ? 而不是抛异常
    2. JSON 输出时按流的真实编码决定 ensure_ascii
       （单字节编码下必须转义，否则 JSON 会变成非法字符序列，机器读不了）
    """
    for name in ('stdout', 'stderr'):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(errors='replace')
        except Exception:
            pass

def _json_ascii() -> bool:
    """当前 stdout 编码能否安全表示中文；不能就转义成 \\uXXXX。"""
    enc = _stream_encoding(sys.stdout)
    if not enc:
        return False
    if any((k in enc for k in _CJK_SAFE)):
        return False
    return True

def _p(obj) -> None:
    print(json.dumps(obj, ensure_ascii=_json_ascii(), indent=2, default=str))

def _result(obj) -> int:
    _p(obj)
    return 1 if isinstance(obj, dict) and obj.get('ok') is False else 0

def _json_arg(value, default=None):
    """接受 JSON 文件路径或内联 JSON 字符串。"""
    import json as _json
    import os as _os
    if value is None:
        return default
    if _os.path.isfile(value):
        with open(value, encoding='utf-8-sig') as fh:
            return _json.load(fh)
    return _json.loads(value)

def _main(argv: list[str] | None=None) -> int:
    _make_output_safe()
    ap = argparse.ArgumentParser(prog='swforge', description='SolidWorks 自动化工具箱')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('gb-check', help='按图样族约定检查关键尺寸与可见标题栏，不认证制造完整性')
    p.add_argument('drawing', nargs='?', default=None)
    p.add_argument('--spec', default=None, help='GBSpec JSON（可列 required_dimensions）')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('gb-tech', help='插入显式技术要求；不自动选择公差/粗糙度')
    p.add_argument('drawing')
    p.add_argument('--items', required=True, help='批准的技术要求字符串数组 JSON 文件')
    p.add_argument('--x', type=float, default=0.04)
    p.add_argument('--y', type=float, default=0.055)
    p = sub.add_parser('gb-title', help='填写现有图框标题字段并回读可见文字')
    p.add_argument('drawing')
    for field in ('name', 'code', 'material', 'scale', 'designer'):
        p.add_argument('--' + field, default=None)
    p = sub.add_parser('position-targets', help='列出位置标注的可见几何基准')
    p.add_argument('drawing')
    p.add_argument('--view', required=True)
    p = sub.add_parser('position-dimension', help='用明确基准和特征添加位置尺寸')
    p.add_argument('drawing')
    p.add_argument('--reference', required=True)
    p.add_argument('--datum', type=int, required=True)
    p.add_argument('--target', type=int, required=True)
    p.add_argument('--axis', choices=['horizontal', 'vertical'], required=True)
    p.add_argument('--x', type=float, required=True)
    p.add_argument('--y', type=float, required=True)
    p = sub.add_parser('selftest', help='实机自检：逐项验证回读、资源、干涉、尺寸等承诺是否真的成立')
    p.add_argument('--only', default=None, help='只跑名称或标题含该词的检查')
    p.add_argument('--keep', action='store_true', help='保留产物目录')
    p.add_argument('--work-dir', default=None, help='指定产物目录')
    p.add_argument('--json', action='store_true', help='输出 JSON')
    p = sub.add_parser('bom', help='从装配体读 BOM 明细（材料/数量），可导出 CSV')
    p.add_argument('assembly', nargs='?', default=None, help='装配体路径，省略则用当前文档')
    p.add_argument('--csv', default=None, help='导出 CSV 的路径')
    p.add_argument('--json', action='store_true', help='输出 JSON')
    p = sub.add_parser('section-view', help='加剖视图')
    p.add_argument('drawing', nargs='?', default=None)
    p.add_argument('--label', default='A')
    p.add_argument('--dir', default='vertical', choices=['vertical', 'horizontal'])
    p.add_argument('--offset', type=float, default=0.2)
    p.add_argument('--offset-y', type=float, default=-0.1)
    p = sub.add_parser('detail-view', help='加局部放大视图')
    p.add_argument('drawing', nargs='?', default=None)
    p.add_argument('--label', default='I')
    p.add_argument('--scale', type=float, default=2.0)
    p.add_argument('--radius', type=float, default=0.012)
    p = sub.add_parser('status', help='一条命令查：代码/CI/待批准/需要你做什么')
    p.add_argument('--offline', action='store_true', help='不查 GitHub 和 PyPI')
    p.add_argument('--json', action='store_true', help='输出 JSON')
    p = sub.add_parser('release-check', help='发版一致性检查：本地/标签/PyPI 三方是否对得上')
    p.add_argument('--offline', action='store_true', help='不查 PyPI')
    p.add_argument('--json', action='store_true', help='输出 JSON')
    sub.add_parser('ping', help='连接探针')
    sub.add_parser('survey', help='量当前文档的包络与实体构成')
    p = sub.add_parser('capabilities', help='本机能力自检')
    p.add_argument('--api', action='store_true', help='额外用反射探测本机 Interop 支持哪些 API（判断版本兼容用）')
    p.add_argument('--sw-dir', default=None, help='手动指定 SolidWorks 安装目录')
    p = sub.add_parser('materials', help='列出内置 GB 牌号并生成/校验 SW 材质库')
    p.add_argument('--ensure', action='store_true', help='生成材质库并返回路径')
    p.add_argument('--force', action='store_true', help='强制重新生成')
    p = sub.add_parser('batch', help='批量出图：一个文件夹的零件 -> 一批工程图')
    p.add_argument('folder', help='模型所在文件夹')
    p.add_argument('--out', default=None, help='输出文件夹（默认与模型同目录）')
    p.add_argument('--pattern', default='*.SLDPRT', help='文件名通配，默认 *.SLDPRT')
    p.add_argument('--recursive', action='store_true', help='递归子目录')
    p.add_argument('--paper', default='A3', choices=['A0', 'A1', 'A2', 'A3', 'A4'])
    p.add_argument('--no-overall', action='store_true', help='不补总尺寸')
    p.add_argument('--pdf', action='store_true', help='同时导出 PDF')
    p.add_argument('--no-skip-existing', action='store_true', help='已存在也重出（默认跳过）')
    p.add_argument('--limit', type=int, default=0, help='最多处理 N 个（0=不限）')
    p.add_argument('--max-documents', type=int, default=8)
    p.add_argument('--report', default=None, help='把结果写成 JSON 报告')
    p.add_argument('--json', action='store_true', help='输出 JSON 而不是人读格式')
    p = sub.add_parser('resources', help='SW 文档数量与内存健康检查；可清扫遗留临时文档')
    p.add_argument('--limit', type=int, default=8, help='文档数上限，默认 8')
    p.add_argument('--warn-ratio', type=float, default=0.75, help='告警线比例，默认 0.75')
    p.add_argument('--mem-warn-mb', type=float, default=2500.0, help='内存告警阈值 MB')
    p.add_argument('--sweep', action='store_true', help='列出可关闭的遗留临时/测试文档')
    p.add_argument('--apply', action='store_true', help='真正关闭（配合 --sweep）')
    p.add_argument('--keep', action='append', default=[], help='永不关闭的路径（可重复）')
    p = sub.add_parser('build', help='按 JSON 描述建零件')
    p.add_argument('spec', help='形位描述 JSON 路径')
    p.add_argument('--out', required=True, help='输出 .SLDPRT 路径')
    p.add_argument('--validate-only', action='store_true', help='只验证描述，不连接 SolidWorks')
    p.add_argument('--no-paint', action='store_true', help='不执行面级配色后处理')
    p.add_argument('--keep-open', action='store_true', help='完成后保留生成的模型文档')
    p.add_argument('--max-documents', type=int, default=8)
    p = sub.add_parser('color', help='按规则给当前零件分色')
    p.add_argument('rules', help='规则 JSON 路径')
    p.add_argument('--dry-run', action='store_true')
    p = sub.add_parser('purge', help='清理导入模型的垃圾体/碎片')
    p.add_argument('--giant', type=float, default=5000.0, help='最大边长阈值 mm')
    p.add_argument('--small', type=float, default=None, help='碎片阈值 mm')
    p.add_argument('--min-y', type=float, default=None, help='碎片最低高度')
    p.add_argument('--apply', action='store_true', help='真的删（默认只列）')
    p = sub.add_parser('draw', help='出工程图')
    p.add_argument('model')
    p.add_argument('--out', default=None)
    p.add_argument('--paper', default='A3')
    p.add_argument('--annotations', action='store_true', help='明确请求 MechDog 自动标注，结果需审核')
    p.add_argument('--keep-open', action='store_true')
    p.add_argument('--max-documents', type=int, default=8)
    p.add_argument('--template', default=None)
    p = sub.add_parser('export', help='导出指定工程图并验证 PDF')
    p.add_argument('drawing')
    p.add_argument('--out', default=None)
    p = sub.add_parser('member', help='建一根标准型材（默认先查素材库，有同型号就复用）')
    p.add_argument('out', help='输出 .sldprt 路径')
    p.add_argument('--shape', default='shs', help='shs方管 / rhs矩型管 / chs圆管 / angle-eq等边角钢 ...')
    p.add_argument('--a', type=float, default=None, help='边长/长边 mm')
    p.add_argument('--b', type=float, default=None, help='短边 mm')
    p.add_argument('--t', type=float, default=None, help='壁厚 mm')
    p.add_argument('--d', type=float, default=None, help='直径 mm（圆管）')
    p.add_argument('--length', type=float, default=1000, help='长度 mm')
    p.add_argument('--axis', default='x', help='x / y / z')
    p.add_argument('--material', default='Q235')
    p.add_argument('--no-library', action='store_true', help='不查素材库，强制现场建模')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('lib-scan', help='扫描 GB 型材素材库，列出分类与数量')
    p.add_argument('--root', default=None, help='素材库根目录（默认自动找）')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('lib-find', help='在素材库里找同型号型材，返回 .SLDLFP 路径')
    p.add_argument('--shape', default='shs', help='shs方管 / rhs矩型管 / chs圆管 / angle-eq等边角钢 ...')
    p.add_argument('--a', type=float, default=None, help='长边或边长 mm')
    p.add_argument('--b', type=float, default=None, help='短边 mm')
    p.add_argument('--t', type=float, default=None, help='壁厚 mm')
    p.add_argument('--d', type=float, default=None, help='直径 mm（圆管/圆钢）')
    p.add_argument('--keyword', default=None, help='按文件名模糊查')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('hole-plate', help='建孔板（原生孔向导；显式孔规格，不推断）')
    p.add_argument('out', help='输出 .sldprt 路径')
    p.add_argument('--spec', required=True, help='孔规格 JSON：{length,width,thickness,holes:[...]}')
    p.add_argument('--material', default='Q235')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('hole-plate-inspect', help='读回孔板几何与孔位')
    p.add_argument('part')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('hole-plate-drawing', help='孔板出图（带孔位置标注）')
    p.add_argument('part')
    p.add_argument('out')
    p.add_argument('--no-positions', action='store_true', help='不标孔位置')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('gdt-check', help='校验形位公差规格（离线，不连 SW）')
    p.add_argument('--spec', required=True, help='GD&T spec JSON')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('gdt-add', help='在图纸上加形位公差框')
    p.add_argument('drawing')
    p.add_argument('--spec', required=True, help='GD&T spec JSON')
    p.add_argument('--reference', required=True, help='原生目标引用')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('assembly-inspect', help='读装配体快照')
    p.add_argument('assembly')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('assembly-bom', help='从装配体算 BOM（合并数量、区分配置）')
    p.add_argument('assembly')
    p.add_argument('--mode', default='parts_only', help='parts_only / top_level / nested')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('assembly-variant-plan', help='规划装配变型（只规划，不动原文件）')
    p.add_argument('source', help='源 .sldasm')
    p.add_argument('out_directory')
    p.add_argument('--spec', default=None, help='{changes,part_changes}')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('assembly-variant-create', help='执行装配变型计划')
    p.add_argument('plan', help='assembly-variant-plan 输出的 JSON')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('bom-table', help='在装配图上插入原生 BOM 表')
    p.add_argument('drawing')
    p.add_argument('--mode', default='parts_only')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('book-snapshot', help='读图册快照')
    p.add_argument('drawing')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('book-review', help='检查图册：越界/重叠/禁放区')
    p.add_argument('drawing')
    p.add_argument('--spec', default=None, help='保留区 JSON')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('book-stamp', help='给图册加版本戳')
    p.add_argument('drawing')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('book-create', help='把多个模型合成一本图册')
    p.add_argument('out', help='输出 .slddrw')
    p.add_argument('models', nargs='+', help='模型路径列表')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('book-layout', help='按给定位置重排图册')
    p.add_argument('source')
    p.add_argument('out')
    p.add_argument('--spec', required=True, help='{placements,reserved_regions}')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('start', help='确保 SolidWorks 在运行；没起来就自己启动它，再连 COM')
    p.add_argument('--wait', type=int, default=180, help='等待就绪的秒数（默认 180）')
    p.add_argument('--exe', default=None, help='显式指定 SLDWORKS.exe 路径')
    p.add_argument('--no-visible', action='store_true', help='不要自动设为可见')
    p.add_argument('--json', action='store_true', help='输出 JSON')
    p = sub.add_parser('install-skill', help='把随包的 agent skill 装进智能体技能目录，之后 SW 操作默认走本库')
    p.add_argument('--target', default=None, help='技能根目录，如 ~/.dsh/skills；省略则自动探测')
    p.add_argument('--force', action='store_true', help='覆盖已存在的')
    p.add_argument('--print', dest='print_only', action='store_true', help='打印 SKILL.md 全文，不写文件')
    p.add_argument('--json', action='store_true', help='输出 JSON')
    p = sub.add_parser('atlas', help='按 JSON 页面描述拼 PDF 图集')
    p.add_argument('spec')
    p.add_argument('--out', required=True)
    p = sub.add_parser('surface-finish', help='添加粗糙度并回读；坐标单位米，Ra 单位 μm')
    p.add_argument('drawing', nargs='?', default=None)
    p.add_argument('--ra', default='3.2')
    p.add_argument('--x', type=float)
    p.add_argument('--y', type=float)
    p.add_argument('--symbol-type', choices=['basic', 'machining', 'no_machining'], default='machining')
    p.add_argument('--view', default=None)
    p.add_argument('--prod-method', default='')
    p.add_argument('--edge', type=int, default=None, help='附着的可见直边索引，先运行 surface-edges')
    p.add_argument('--edge-fraction', type=float, default=0.5)
    p.add_argument('--leader', action='store_true', help='用引线指向指定轮廓边')
    p.add_argument('--save', action='store_true', help='回读成功后保存源工程图')
    p = sub.add_parser('dimensions', help='列出当前图纸尺寸完整名称、视图和值')
    p.add_argument('drawing', nargs='?', default=None)
    p = sub.add_parser('surface-edges', help='枚举视图可见直边索引和图纸坐标，用于粗糙度附着')
    p.add_argument('drawing', nargs='?', default=None)
    p.add_argument('--view', default=None)
    p = sub.add_parser('tolerance', help='设置明确给定的尺寸公差并回读，偏差单位毫米')
    p.add_argument('drawing', nargs='?', default=None)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--dim', default=None)
    group.add_argument('--value', type=float, default=None)
    p.add_argument('--view', default=None)
    p.add_argument('--type', choices=['symmetric', 'bilateral', 'limit', 'fit', 'none'], default='symmetric')
    p.add_argument('--upper', type=float, default=None)
    p.add_argument('--lower', type=float, default=None)
    p.add_argument('--fit', default=None)
    p.add_argument('--save', action='store_true', help='回读成功后保存源工程图')
    p = sub.add_parser('mate-faces', help='只读枚举装配圆柱面/平面的持久引用，坐标单位毫米')
    p.add_argument('assembly', nargs='?', default=None)
    p.add_argument('--component', default=None)
    p.add_argument('--kind', choices=['cylinder', 'plane'], default=None)
    p.add_argument('--out', default=None, help='把面清单写入JSON文件')
    p = sub.add_parser('mate', help='按JSON中的明确面引用建立同心/重合配合并回读')
    p.add_argument('assembly', nargs='?', default=None)
    p.add_argument('--spec', required=True, help='包含 mates 列表的JSON文件')
    p.add_argument('--inspect', action='store_true', help='只读检查指定配合是否存在且几何正确')
    p.add_argument('--save', action='store_true', help='全部回读成功后保存装配体')
    p = sub.add_parser('parameters', help='Read exact linear model parameter keys')
    p.add_argument('part')
    p = sub.add_parser('drawing-circles', help='Read explicit visible circular edges')
    p.add_argument('drawing')
    p.add_argument('--view', required=True)
    p = sub.add_parser('diameter', help='Add native diameter to exact circle JSON; coordinates metres')
    p.add_argument('drawing')
    p.add_argument('--circle', required=True)
    p.add_argument('--x', type=float, required=True)
    p.add_argument('--y', type=float, required=True)
    p = sub.add_parser('variant', help='Create a verified new part without editing source')
    p.add_argument('source')
    p.add_argument('--out', required=True)
    p.add_argument('--spec', required=True, help='JSON object: parameters, material, configuration')
    p.add_argument('--drawing')
    p.add_argument('--summary-csv')
    p.add_argument('--keep-open', action='store_true')
    p = sub.add_parser('audit-drawing', help='Read-only drawing checks with explicit coverage')
    p.add_argument('drawing')
    p.add_argument('--required-property', action='append', default=[])
    p = sub.add_parser('layout-plan', help='Read-only three-view layout proposal')
    p.add_argument('drawing')
    for command in ('weldment-frame', 'spur-gear'):
        p = sub.add_parser(command, help='Native mechanical family, mm; explicit JSON parameters')
        p.add_argument('--spec', required=True)
        p.add_argument('--out', required=True)
        p.add_argument('--drawing')
        p.add_argument('--keep-open', action='store_true')
    p = sub.add_parser('mechanical-inspect', help='Read native features, bodies, cut list and mass')
    p.add_argument('part')
    p = sub.add_parser('mechanical-drawing', help='New family drawing with native cut list or gear table')
    p.add_argument('part')
    p.add_argument('--out', required=True)
    p = sub.add_parser('mechanical-variant', help='Regenerate a native mechanical family copy; source protected')
    p.add_argument('source')
    p.add_argument('--spec', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--drawing')
    for command in ('template-validate', 'gb-styles', 'general-tolerance'):
        p = sub.add_parser(command, help='Explicit GB profile and evidence checks')
        p.add_argument('target')
        p.add_argument('--apply', action='store_true')
        if command == 'raster-review':
            p.add_argument('--paper-mm', nargs=2, type=float, required=True)
            p.add_argument('--regions', required=True, help='JSON native annotation boxes, sheet metres')
    p = sub.add_parser('capability-matrix', help='Single-host acceptance matrix; no cross-version support claim')
    p.add_argument('--connect', action='store_true')
    p = sub.add_parser('ledger', help='Recheck freshness of an existing delivery ledger')
    p.add_argument('path')
    p = sub.add_parser('approve-preview', help='Preview hash only; this does not authorize a destructive operation')
    p.add_argument('request', help='JSON: name,args,document_path,before,after')
    p.add_argument('--out', required=True)
    p = sub.add_parser('approve-apply', help='Issue one-use TTL token after explicit confirmation of the preview')
    p.add_argument('preview')
    p.add_argument('--confirmed', action='store_true')
    args = ap.parse_args(argv)
    if args.cmd == 'capability-matrix':
        from .capability_matrix import host_status
        return _result(host_status(args.connect))
    if args.cmd == 'ledger':
        from .core.ledger import delivery_manifest
        with open(args.path, encoding='utf-8') as f:
            stored = json.load(f)
        return _result(delivery_manifest(stored['entries']))
    if args.cmd in ('approve-preview', 'approve-apply'):
        from .core.approval import preview_operation, ApprovalStore
        from .guard import active_path, switches_detected
        from .server import mcp
        if args.cmd == 'approve-preview':
            with open(args.request, encoding='utf-8') as f:
                req = json.load(f)
            row = mcp._gateway.registry[req['name']]
            canonical = row['model'].model_validate(req['args']).model_dump()
            result = preview_operation(req['name'], canonical, req['document_path'], req['before'], req['after'], active_path=active_path(), switch_count=switches_detected()['count'])
            with open(args.out, 'x', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        else:
            with open(args.preview, encoding='utf-8') as f:
                preview = json.load(f)
            if not active_path() or os.path.normcase(active_path()) != os.path.normcase(preview['document_path']):
                raise ValueError('Active document changed since preview')
            result = mcp._gateway.approvals.issue(preview, confirmed=args.confirmed)
        return _result(dict(ok=True, **result))
    if args.cmd in ('template-validate', 'gb-styles', 'general-tolerance'):
        from .gb_styles import validate_gb_template, read_gb_styles, apply_gb_styles
        if args.cmd == 'template-validate':
            result = validate_gb_template(args.target)
        elif args.cmd == 'gb-styles':
            result = (apply_gb_styles if args.apply else read_gb_styles)(args.target)
        elif args.cmd == 'general-tolerance':
            from .gb_standards import general_tolerance_note
            result = {'ok': True, 'note': general_tolerance_note(args.target)}
        _p(result)
        return 0 if result.get('ok') else 1
    if args.cmd in ('weldment-frame', 'spur-gear'):
        from .mechanical import create_weldment_frame, create_spur_gear
        with open(args.spec, encoding='utf8') as stream:
            spec = json.load(stream)
        fun = create_weldment_frame if args.cmd == 'weldment-frame' else create_spur_gear
        return _result(fun(args.out, **spec, drawing_path=args.drawing, keep_open=args.keep_open))
    if args.cmd == 'mechanical-inspect':
        from .mechanical import inspect_mechanical
        return _result(inspect_mechanical(args.part))
    if args.cmd == 'gb-check':
        from .gb_check import check_gb_drawing, GBSpec, format_report
        spec = None
        if args.spec:
            with open(args.spec, encoding='utf8') as stream:
                spec = GBSpec(**json.load(stream))
        result = check_gb_drawing(args.drawing, spec)
        if args.json:
            return _result(result)
        print(format_report(result))
        return 1 if result['status'] == 'FAILED' else 0
    if args.cmd == 'position-targets':
        from .position_dimensions import list_position_targets
        return _result(list_position_targets(args.drawing, args.view))
    if args.cmd == 'position-dimension':
        from .position_dimensions import add_position_dimension
        with open(args.reference, encoding='utf8') as stream:
            reference = json.load(stream)
        return _result(add_position_dimension(args.drawing, reference, args.datum, args.target, axis=args.axis, x=args.x, y=args.y))
    if args.cmd == 'gb-tech':
        from .gb_notes import add_tech_requirements
        with open(args.items, encoding='utf8') as stream:
            items = json.load(stream)
        return _result(add_tech_requirements(args.drawing, items, x_m=args.x, y_m=args.y))
    if args.cmd == 'gb-title':
        from .gb_notes import fill_title_block
        return _result(fill_title_block(args.drawing, **{f: getattr(args, f) for f in ('name', 'code', 'material', 'scale', 'designer')}))
    if args.cmd == 'mechanical-drawing':
        from .mechanical import mechanical_drawing
        return _result(mechanical_drawing(args.part, args.out))
    if args.cmd == 'mechanical-variant':
        from .mechanical import create_mechanical_variant
        with open(args.spec, encoding='utf8') as stream:
            spec = json.load(stream)
        return _result(create_mechanical_variant(args.source, args.out, parameters=spec, drawing_path=args.drawing))
    if args.cmd == 'drawing-circles':
        from .circle_dimensions import list_drawing_circles
        return _result(list_drawing_circles(args.drawing, args.view))
    if args.cmd == 'diameter':
        from .circle_dimensions import add_diameter_dimension
        with open(args.circle, encoding='utf8') as stream:
            circle = json.load(stream)
        return _result(add_diameter_dimension(args.drawing, circle, args.x, args.y))
    if args.cmd == 'parameters':
        from .variants import list_model_parameters
        return _result(list_model_parameters(args.part))
    if args.cmd == 'variant':
        from .variants import create_variant
        with open(args.spec, encoding='utf8') as stream:
            spec = json.load(stream)
        if not isinstance(spec, dict) or set(spec) - {'parameters', 'material', 'configuration'}:
            return _result({'ok': False, 'error': 'Variant spec contains unknown fields'})
        return _result(create_variant(args.source, args.out, **spec, drawing_path=args.drawing, summary_csv=args.summary_csv, keep_open=args.keep_open))
    if args.cmd in ('audit-drawing', 'layout-plan'):
        from .drawing_review import audit_drawing, suggest_drawing_layout
        result = audit_drawing(args.drawing, args.required_property) if args.cmd == 'audit-drawing' else suggest_drawing_layout(args.drawing)
        code = _result(result)
        return 1 if result.get('passed') is False else code
    if args.cmd == 'mate-faces':
        from .mate_faces import list_mate_faces
        result = list_mate_faces(args.assembly, component=args.component, kind=args.kind)
        if args.out:
            with open(args.out, 'w', encoding='utf8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
        return _result(result)
    if args.cmd == 'mate':
        from .mate_faces import apply_face_mates, inspect_face_mates
        with open(args.spec, encoding='utf8') as stream:
            spec = json.load(stream)
        action = inspect_face_mates if args.inspect else apply_face_mates
        result = action(args.assembly, mates=spec['mates'])
        if result['ok'] and args.save:
            from .session import get_session, _value
            from .drawing import _save_as
            md = get_session().sw().ActiveDoc
            path = str(_value(md, 'GetPathName'))
            if os.path.normcase(path) != os.path.normcase(result['assembly_path']):
                result.update(ok=False, error='保存前活动装配已被切换，停止保存')
            else:
                saved, error, warning = _save_as(md, path)
                result['save'] = dict(ok=bool(saved and (not error)), error_code=error, warning_code=warning)
                if not result['save']['ok']:
                    result.update(ok=False, error='显式配合已在内存中完成，但保存失败')
        return _result(result)
    if args.cmd in ('surface-finish', 'surface-edges', 'dimensions', 'tolerance'):
        from .annotations import add_surface_finish, list_surface_edges, list_dimensions, set_tolerance
        if args.cmd == 'surface-edges':
            return _result({'ok': True, 'edges': list_surface_edges(args.drawing, args.view)})
        if args.cmd == 'dimensions':
            return _result({'ok': True, 'dimensions': list_dimensions(args.drawing)})
        if args.cmd == 'surface-finish':
            result = add_surface_finish(args.drawing, x=args.x, y=args.y, ra=args.ra, symbol_type=args.symbol_type, view_name=args.view, prod_method=args.prod_method, edge_index=args.edge, edge_fraction=args.edge_fraction, leader=args.leader)
        else:
            result = set_tolerance(args.drawing, dim_name=args.dim, dim_value=args.value, tol_type=args.type, upper=args.upper, lower=args.lower, fit=args.fit, view_name=args.view)
        if result['ok'] and args.save:
            from .annotations import _drawing
            from .drawing import _save_as
            from .session import _value
            _, md = _drawing(args.drawing)
            path = str(_value(md, 'GetPathName') or '')
            if not path:
                result.update(ok=False, error='工程图尚未命名，无法保存；标注仍在内存中')
            else:
                saved, error, warning = _save_as(md, path)
                result['save'] = {'ok': saved, 'error_code': error, 'warning_code': warning}
                if not saved or error:
                    result.update(ok=False, error=f'保存工程图失败：{error}')
        return _result(result)
    if args.cmd == 'materials':
        from .gb_materials import GB_MATERIALS, ensure_library, library_path
        rows = [{'grade': n, 'density_kg_m3': v[0], 'elastic_pa': v[1], 'poisson': v[2], 'note': v[3]} for n, v in sorted(GB_MATERIALS.items())]
        out = {'ok': True, 'count': len(rows), 'grades': rows, 'library': library_path()}
        if args.ensure:
            out['library'] = ensure_library(force=args.force)
        return _result(out)
    if args.cmd == 'capabilities':
        return _cmd_capabilities(args)
    if args.cmd == 'batch':
        return _cmd_batch(args)
    if args.cmd == 'resources':
        from .resources import resource_status, sweep_documents
        out = resource_status(limit=args.limit, warn_ratio=args.warn_ratio, mem_warn_mb=args.mem_warn_mb)
        if args.sweep:
            out['sweep'] = sweep_documents(dry_run=not args.apply, keep=args.keep)
            if args.apply:
                out.update({k: out['sweep'][k] for k in ('document_count', 'headroom')} if False else {})
                out = resource_status(limit=args.limit, warn_ratio=args.warn_ratio, mem_warn_mb=args.mem_warn_mb)
                out['sweep'] = sweep_documents(dry_run=True, keep=args.keep)
        return _result(out)
    if args.cmd == 'selftest':
        return _cmd_selftest(args)
    if args.cmd == 'bom':
        return _cmd_bom(args)
    if args.cmd == 'section-view':
        from .views_extra import add_section_view
        _p(add_section_view(args.drawing, label=args.label, direction=args.dir, offset=args.offset, offset_y=args.offset_y))
        return 0
    if args.cmd == 'detail-view':
        from .views_extra import add_detail_view
        _p(add_detail_view(args.drawing, label=args.label, scale=args.scale, radius=args.radius))
        return 0
    if args.cmd == 'status':
        return _cmd_status(args)
    if args.cmd == 'release-check':
        return _cmd_release_check(args)
    if args.cmd == 'ping':
        from .session import get_session
        return _result(get_session().ping())
    if args.cmd == 'survey':
        from .cleanup import survey
        return _result(survey())
    if args.cmd == 'capabilities':
        from .drawing import have_mechdog
        info = {'swforge': __import__('swforge').__version__, 'mechdog': have_mechdog(), 'python': sys.version.split()[0], 'platform': sys.platform}
        try:
            from .session import get_session
            info['sw'] = get_session().ping()
        except Exception as exc:
            info['sw'] = {'ok': False, 'error': str(exc)}
        info['ok'] = bool(info['sw'].get('ok'))
        return _result(info)
    if args.cmd == 'build':
        from .spec import builder_from_spec
        with open(args.spec, encoding='utf-8') as fh:
            spec = json.load(fh)
        b = builder_from_spec(args.out, spec)
        if args.validate_only:
            return _result({'ok': True, 'path': b.path, 'validated': True, 'source_bytes': len(b.render_cs().encode('utf-8'))})
        return _result(b.build(paint=not args.no_paint, keep_open=args.keep_open, max_documents=args.max_documents).__dict__)
    if args.cmd == 'color':
        from .colors import FaceRule, apply_rules
        with open(args.rules, encoding='utf-8') as fh:
            spec = json.load(fh)
        rules = [FaceRule(r['name'], tuple(r['color']), **r.get('cond', {})) for r in spec['rules']]
        return _result(apply_rules(spec.get('part', ''), rules, dry_run=args.dry_run))
    if args.cmd == 'purge':
        from .cleanup import purge_giant, purge_small
        from .session import get_session
        md = get_session().sw().ActiveDoc
        if md is None:
            print('没有打开的文档', file=sys.stderr)
            return 1
        if args.small is not None:
            return _result(purge_small(md, args.small, args.min_y, dry_run=not args.apply))
        else:
            return _result(purge_giant(md, args.giant, dry_run=not args.apply))
    if args.cmd == 'draw':
        from .drawing import produce
        return _result(produce(args.model, args.out, args.paper, annotations=args.annotations, keep_open=args.keep_open, max_documents=args.max_documents, template=args.template))
    if args.cmd == 'export':
        from .drawing import export_pdf
        return _result(export_pdf(args.drawing, args.out))
    if args.cmd == 'hole-plate':
        from .hole_families import create_hole_plate
        spec = _json_arg(args.spec, {})
        return _result(create_hole_plate(args.out, length=spec.get('length', 120), width=spec.get('width', 80), thickness=spec.get('thickness', 20), holes=spec.get('holes') or [], material=args.material))
    if args.cmd == 'hole-plate-inspect':
        from .hole_families import inspect_hole_plate
        return _result(inspect_hole_plate(args.part))
    if args.cmd == 'hole-plate-drawing':
        from .hole_annotations import hole_plate_drawing
        return _result(hole_plate_drawing(args.part, args.out, positions=not args.no_positions))
    if args.cmd == 'gdt-check':
        from .gdandt import validate_gdt
        try:
            return _result({'ok': True, 'spec': validate_gdt(_json_arg(args.spec, {}))})
        except Exception as exc:
            return _result({'ok': False, 'error': f'{type(exc).__name__}: {exc}'})
    if args.cmd == 'gdt-add':
        from .gdandt import add_geometric_tolerance
        return _result(add_geometric_tolerance(args.drawing, args.reference, _json_arg(args.spec, {})))
    if args.cmd == 'assembly-inspect':
        from .assembly_workflows import inspect_assembly
        return _result(inspect_assembly(args.assembly))
    if args.cmd == 'assembly-bom':
        from .assembly_workflows import inspect_assembly, assembly_bom
        snap = inspect_assembly(args.assembly)
        if not snap.get('ok'):
            return _result(snap)
        return _result(assembly_bom(snap, mode=args.mode))
    if args.cmd == 'assembly-variant-plan':
        from .assembly_workflows import plan_assembly_variant
        spec = _json_arg(args.spec, {}) or {}
        return _result(plan_assembly_variant(args.source, args.out_directory, changes=spec.get('changes'), part_changes=spec.get('part_changes')))
    if args.cmd == 'assembly-variant-create':
        from .assembly_workflows import create_assembly_variant
        return _result(create_assembly_variant(_json_arg(args.plan, {})))
    if args.cmd == 'bom-table':
        from .assembly_bom_table import insert_assembly_bom
        return _result(insert_assembly_bom(args.drawing, mode=args.mode))
    if args.cmd == 'book-snapshot':
        from .drawing_books import drawing_book_snapshot
        return _result(drawing_book_snapshot(args.drawing))
    if args.cmd == 'book-review':
        from .drawing_books import review_drawing_book
        return _result(review_drawing_book(args.drawing, reserved_regions=_json_arg(args.spec)))
    if args.cmd == 'book-stamp':
        from .drawing_books import stamp_drawing_book
        return _result(stamp_drawing_book(args.drawing))
    if args.cmd == 'book-create':
        from .drawing_books import create_drawing_book
        return _result(create_drawing_book(args.models, args.out))
    if args.cmd == 'book-layout':
        from .drawing_books import layout_drawing_book
        spec = _json_arg(args.spec, {})
        return _result(layout_drawing_book(args.source, args.out, spec.get('placements'), reserved_regions=spec.get('reserved_regions')))
    if args.cmd == 'member':
        from .mechanical import create_standard_member
        return _result(create_standard_member(args.out, shape=args.shape, a=args.a, b=args.b, t=args.t, d=args.d, length=args.length, axis=args.axis, material=args.material, use_library=not args.no_library))
    if args.cmd == 'lib-scan':
        from .library import MaterialLibrary
        lib = MaterialLibrary([args.root] if args.root else None)
        info = lib.index()
        info['categories'] = lib.categories()
        return _result(info)
    if args.cmd == 'lib-find':
        from .library import MaterialLibrary
        lib = MaterialLibrary()
        if args.keyword:
            hits = lib.search(args.keyword, limit=20)
            return _result({'ok': True, 'keyword': args.keyword, 'hits': hits})
        r = lib.resolve_section(shape=args.shape, a=args.a, b=args.b, t=args.t, d=args.d)
        return _result(r)
    if args.cmd == 'start':
        from .startup import ensure_running
        return _result(ensure_running(exe=args.exe, wait_s=args.wait, visible=not getattr(args, 'no_visible', False)))
    if args.cmd == 'install-skill':
        from .skill_install import install, print_bundle_text
        if getattr(args, 'print_only', False):
            print(print_bundle_text())
            return 0
        r = install(args.target, force=args.force)
        return _result(r)
    if args.cmd == 'atlas':
        from .drawing import make_atlas
        with open(args.spec, encoding='utf-8') as fh:
            spec = json.load(fh)
        return _result(make_atlas(spec['pages'], args.out, title=spec.get('title', '技术图集'), subtitle=spec.get('subtitle', ''), cover_items=[tuple(x) for x in spec.get('cover_items', [])], paper=spec.get('paper', 'A3')))
    return 1

def _cmd_bom(args):
    """读装配体的 BOM 明细。"""
    from .bom import collect_bom, bom_to_csv, bom_to_markdown
    r = collect_bom(args.assembly)
    if args.json:
        _p(r)
        return 0 if r.get('ok') else 1
    if not r.get('ok'):
        print(f"  失败：{r.get('error')}")
        return 1
    print()
    print(f"  装配：{r['assembly']}")
    print(f"  种类 {r['distinct_parts']} 项，共计 {r['total_items']} 件")
    print()
    print(bom_to_markdown(r['rows']))
    print()
    if r.get('missing_material'):
        print(f"  ⚠ 这些零件没有材料：{', '.join(r['missing_material'])}")
        print(f"    {r.get('note', '')}")
    if args.csv:
        bom_to_csv(r['rows'], args.csv)
        print(f'  已导出 CSV：{args.csv}')
    return 0

def _cmd_status(args):
    """一条命令查全部状态。有事项待处理时以非 0 退出。"""
    from .status import check_status, format_status
    s = check_status(online=not args.offline)
    if args.json:
        _p(s)
        return 0 if s.get('ok') else 1
    print(format_status(s))
    return 0 if s.get('ok') else 1

def _cmd_release_check(args):
    """发版一致性检查。发现问题以非 0 退出。"""
    from .release_check import check_release, format_report
    r = check_release(online=not args.offline)
    if args.json:
        _p(r)
        return 0 if r.get('ok') else 1
    print(format_report(r))
    return 0 if r.get('ok') else 1

def _cmd_selftest(args):
    """实机自检。逐项跑，任何一项失败就以非 0 退出。"""
    from .selftest import run_selftest

    def show(one):
        mark = 'PASS' if one['ok'] else 'FAIL'
        print(f"  [{mark}] {one['title']:<26} {one['elapsed_s']:>5.2f}s  {one['detail']}")
    if not args.json:
        print()
        print('  swforge 实机自检')
        print('  每一项都在真实 SolidWorks 上跑，读出结果再判定')
        print()
    r = run_selftest(work_dir=args.work_dir, only=args.only, keep=args.keep, progress=None if args.json else show)
    if args.json:
        _p(r)
        return 0 if r.get('ok') else 1
    print()
    if r.get('error'):
        print(f"  错误：{r['error']}")
        return 1
    print(f"  结果：{r['passed']} 通过 / {r['failed']} 失败   耗时 {r['elapsed_s']:.1f}s")
    print(f"  环境：swforge {r['swforge']}  SolidWorks {r['sw_version']}")
    if r.get('work_dir'):
        print(f"  产物：{r['work_dir']}")
    if r.get('ok'):
        print('  全部通过 —— 本机这些能力都是实测可用的')
    else:
        failed = [x for x in r['results'] if not x['ok']]
        print()
        print('  失败项说明：')
        for x in failed:
            print(f"    - {x['title']}：{x['detail']}")
            if x.get('why'):
                print(f"      这一项对应的问题：{x['why']}")
    return 0 if r.get('ok') else 1

def _cmd_capabilities(args):
    """本机能力自检。--api 时额外探测 Interop 支持的 API 清单。"""
    from .session import get_session
    out = {'swforge': ''}
    try:
        from . import __version__ as _v
        out['swforge'] = _v
    except Exception:
        pass
    out['python'] = sys.version.split()[0]
    out['platform'] = sys.platform
    try:
        ping = get_session().ping()
        out['sw'] = ping
        out['connected'] = bool(ping.get('ok'))
    except Exception as exc:
        out['sw'] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
        out['connected'] = False
    if args.api:
        try:
            from .probe import probe_api
            probe = probe_api(sw_dir=args.sw_dir)
            out['api'] = probe
            if probe.get('ok'):
                out['verdict'] = '本机支持完整功能' if not probe.get('missing') else f"缺失 {len(probe['missing'])} 个 API，见 api.missing"
            else:
                out['verdict'] = f"探测失败：{probe.get('error')}"
        except Exception as exc:
            out['api'] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
            out['verdict'] = '探测异常'
    out['ok'] = out.get('connected', False)
    return _result(out)

def _cmd_batch(args):
    """批量出图：一个文件夹的零件 -> 一批带 GB 图框的工程图。"""
    import os as _os
    from .batch import batch_drawings, write_report

    def show(idx, total, item):
        bar = f'[{idx}/{total}]'
        name = _os.path.basename(item.model)
        if item.skipped:
            print(f'{bar} 跳过  {name}（图已存在）', flush=True)
        elif item.ok:
            extra = f'  尺寸 {item.dims}'
            if item.overall_done:
                extra += f'（总尺寸 {item.overall_done}）'
            if item.pdf_ok:
                extra += '  +PDF'
            print(f'{bar} ✓     {name}{extra}  {item.seconds:.1f}s', flush=True)
        else:
            print(f'{bar} ✗     {name}  {item.error[:80]}', flush=True)
    res = batch_drawings(args.folder, out_dir=args.out, pattern=args.pattern, recursive=args.recursive, paper=args.paper, overall=not args.no_overall, pdf=args.pdf, skip_existing=not args.no_skip_existing, limit=args.limit, max_documents=args.max_documents, progress=None if args.json else show)
    if args.report:
        write_report(res, args.report)
        if not args.json:
            print(f'\n报告: {args.report}')
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res['ok'] else 1
    print()
    print(f"  合计 {res['total']} 个模型")
    print(f"  成功 {res['succeeded']}   失败 {res['failed']}   跳过 {res['skipped']}   PDF {res['pdf_ok']}")
    print(f"  耗时 {res['seconds']:.1f} 秒")
    if res['failed']:
        print()
        print('  失败的：')
        for it in res['items']:
            if not it['ok']:
                print(f"    {_os.path.basename(it['model'])}: {it['error']}")
    return 0 if res['ok'] else 1

def main(argv: list[str] | None=None) -> int:
    _make_output_safe()
    try:
        return _main(argv)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _p({'ok': False, 'error': f'{type(exc).__name__}: {exc}'})
        return 1
if __name__ == '__main__':
    raise SystemExit(main())
