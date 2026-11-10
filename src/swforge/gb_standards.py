"""Explicit supported numeric tables; never infer manufacturing requirements.

Table coverage is deliberately finite: H6/H7/H8/h6/h7/h8/g6, 3 < D <= 500 mm.
Unlisted fits are unsupported, not automatically declared nonconforming.
"""
import math,re

RA_SERIES=(.0125,.025,.05,.1,.2,.4,.8,1.6,3.2,6.3,12.5,25.,50.,100.)
BOUNDS=(6,10,18,30,50,80,120,180,250,315,400,500)
IT={6:(8,9,11,13,16,19,22,25,29,32,36,40),
    7:(12,15,18,21,25,30,35,40,46,52,57,63),
    8:(18,22,27,33,39,46,54,63,72,81,89,97)}
G_UPPER=(-4,-5,-6,-7,-9,-10,-12,-14,-15,-17,-18,-20)


def ra_series_valid(ra):
    try:
        return not isinstance(ra,bool) and any(math.isclose(float(ra),x,rel_tol=0,abs_tol=1e-10) for x in RA_SERIES)
    except (TypeError,ValueError):return False


def fit_deviation(fit,nominal_mm):
    if isinstance(nominal_mm,bool):raise ValueError('Finite nominal size required')
    size=float(nominal_mm)
    if not math.isfinite(size) or not 3<size<=500:raise ValueError('Supported fit table: 3 < nominal_mm <= 500')
    index=next(i for i,end in enumerate(BOUNDS) if size<=end)
    result={}
    parts=str(fit).split('/')
    if len(parts)>2 or len(parts)==2 and (not parts[0].startswith('H') or not parts[1].startswith(('h','g'))):
        raise ValueError('Pair must be hole/shaft in that order')
    for code in parts:
        if not re.fullmatch(r'(?:[Hh][678]|g6)',code):raise ValueError('Unsupported fit table code: '+code)
        width=IT[int(code[-1])][index]
        low,high=(0,width) if code[0]=='H' else (-width,0) if code[0]=='h' else (G_UPPER[index]-width,G_UPPER[index])
        result[code]={'lower_mm':low/1000,'upper_mm':high/1000}
    if len(result) not in (1,2):raise ValueError('One code or a hole/shaft pair required')
    return {'ok':True,'nominal_mm':size,'deviations':result,'standard':'GB/T 1800.2-2020',
            'coverage':'supported codes only; not an automatic fit recommendation'}


def general_tolerance_note(cls):
    if cls not in ('f','m','c','v'):raise ValueError('Explicit general tolerance class f/m/c/v required')
    return '未注线性和角度尺寸公差按 GB/T 1804-'+cls+'；倒圆半径、倒角高度及适用范围按批准的设计要求执行'
