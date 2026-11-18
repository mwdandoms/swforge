"""Validate known-gap, touching and overlapping cubes in a selected SW version."""
import argparse
import dataclasses
import json
import os
from pathlib import Path
import traceback


def main():
    p=argparse.ArgumentParser();p.add_argument('--year',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();os.environ['SWFORGE_SW_YEAR']=a.year
    import swforge
    from swforge.session import _value
    root=Path(a.out).resolve();root.mkdir(parents=True,exist_ok=False)
    sw=swforge.get_session().sw();before=swforge.document_inventory(sw)
    assert before['document_count']<3,'Insufficient document capacity'
    report=dict(version=swforge.__version__,module=swforge.__file__,revision=str(_value(sw,'RevisionNumber')),before=before,cases={})
    def close_owned():
        for row in swforge.document_inventory(sw)['documents']:
            if row.get('path') and Path(row['path']).parent==root:sw.CloseDoc(row['title'])
    try:
        part=root/'cube.SLDPRT'
        built=swforge.PartBuilder(str(part)).box('cube',0,20,0,20,0,20).build(keep_open=False,max_documents=5)
        report['part']=dataclasses.asdict(built);assert built.ok,built.error
        parameters=swforge.list_model_parameters(str(part))
        key=next(r['key'] for r in parameters['parameters'] if r['key'].startswith('ProfileHeight@'))
        changed=swforge.set_parameters(str(part),{key:21},save=True,backup=False)
        report['square_edit']=changed;assert changed['ok'],changed
        checked=swforge.inspect_feature_tree(str(part))
        report['square_edited_reopened']=checked
        assert checked['ok'] and abs(checked['volume_mm3']-8400)<.01,checked
        restored=swforge.set_parameters(str(part),{key:20},save=True,backup=False)
        report['square_restore']=restored;assert restored['ok'],restored
        close_owned()
        for name,x,distance,volume in [('gap',30,10,0),('touch',20,0,0),('overlap',15,0,2000)]:
            row=report['cases'][name]={}
            try:
                asm=root/(name+'.SLDASM')
                result=(swforge.AssemblyBuilder(str(asm),keep_open=False).add(str(part),fixed=True)
                        .add(str(part),x=x).build(max_documents=5))
                row['assembly']=result;assert result['ok'],result
                checked=swforge.check_clearance(str(asm),minimum_mm=1)
                row['clearance']=checked;assert checked['ok'],checked
                assert len(checked['pairs'])==1,checked
                pair=checked['pairs'][0]
                assert abs(pair['clearance_mm']-distance)<.01,pair
                assert abs(pair['interference_volume_mm3']-volume)<.1,pair
                assert pair['verdict']=={'gap':'clear','touch':'touch','overlap':'interference'}[name],pair
                assert checked['meets_all']==(name=='gap'),checked
                row['passed']=True
            except Exception as exc:row.update(passed=False,error=str(exc),traceback=traceback.format_exc())
            finally:close_owned()
            print(name,row['passed'],flush=True)
    finally:
        close_owned();report['after']=swforge.document_inventory(sw)
        report['passed']=(len(report['cases'])==3 and all(r.get('passed') for r in report['cases'].values()) and report['after']['documents']==before['documents'])
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
