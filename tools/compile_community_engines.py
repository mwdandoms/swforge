"""Compile typed Community engines against a selected installed Interop; no CAD calls."""
import argparse
import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import uuid


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--year',required=True);ap.add_argument('--out',required=True)
    args=ap.parse_args();os.environ['SWFORGE_SW_YEAR']=args.year
    import swforge
    from swforge.sw_target import install_dir,native_source
    root=Path(args.out).resolve();root.mkdir(parents=True,exist_ok=False)
    source_root=Path(swforge.__file__).parent
    directory=Path(install_dir());dll=directory/'SolidWorks.Interop.sldworks.dll';const=directory/'SolidWorks.Interop.swconst.dll'
    cases=[]
    for p in source_root.glob('*.py'):
        tree=ast.parse(p.read_text(encoding='utf8'))
        for n in tree.body:
            if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str):
                code=n.value.value
                if 'public class __CLASS__' not in code or 'using System' not in code:continue
                if p.stem=='modeling':continue  # Compile rendered native and helical cases below.
                if '__SKETCH_HELPERS__' in code:
                    module=importlib.import_module('swforge.'+p.stem)
                    # Use the production helper composition rather than the raw template.
                    code=module.engine()
                name=p.stem+'_'+n.targets[0].id
                replacements={'__CLASS__':'Compile_'+uuid.uuid4().hex,'__PID__':'0','__PATH__':'""',
                    '__GAP__':'10','__INTERNAL__':'6','__MINGAP__':'.1','__SPECS__':'', '__SPECSCOUNT__':'0'}
                for a,b in replacements.items():code=code.replace(a,b)
                cases.append((name,native_source(code)))
    b=swforge.PartBuilder(str(root/'unused.SLDPRT')).box('plate',0,120,0,10,0,80)
    cases.append(('modeling_native',b.render_cs()))
    b=swforge.PartBuilder(str(root/'unused_helical.SLDPRT'))
    b.helix_spring('coil',wire_diameter=2,mean_diameter=20,height=45,turns=6)
    cases.append(('modeling_geometry',b.render_cs()))
    report=dict(year=args.year,version=swforge.__version__,module=swforge.__file__,interop=str(dll),cases={})
    for name,code in cases:
        # Add-Type emits a separate assembly for every source. Avoid shared helper names.
        code=code.replace('SwforgeConnection','SwforgeConnection_'+uuid.uuid4().hex)
        p=root/(name+'.cs');p.write_text(code,encoding='utf8')
        ps=root/(name+'.ps1')
        quote=lambda s:str(s).replace("'","''")
        ps.write_text("$ErrorActionPreference='Stop'\n"+
            f"[System.Reflection.Assembly]::LoadFrom('{quote(dll)}') | Out-Null\n"+
            f"Add-Type -TypeDefinition ([IO.File]::ReadAllText('{quote(p)}')) -ReferencedAssemblies '{quote(dll)}','{quote(const)}','System.Web.Extensions','System.Core'\n",encoding='utf-8-sig')
        r=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ps)],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60)
        report['cases'][name]=dict(passed=r.returncode==0,error=r.stderr[-16000:])
        print(name,r.returncode==0,flush=True)
    report['passed']=all(x['passed'] for x in report['cases'].values())
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
