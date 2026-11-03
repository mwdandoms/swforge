"""v0.4 SW checks: only generated artifacts are closed by the test guard."""
import json
import os
import uuid
import pytest

from test_v03_integration import live,build_measured
from dsh_sw_toolkit import PartBuilder,drawing
from dsh_sw_toolkit.modeling import preview_edges
from dsh_sw_toolkit.resources import document_inventory

pytestmark=pytest.mark.sw


def test_read_only_edge_preview(live):
    _,result,_=build_measured(live,'edge_preview',lambda b:b.box('block',0,40,0,30,0,25))
    preview=preview_edges(result.path,'block',{'axis':'y','min_length_mm':29,'max_length_mm':31})
    assert preview['selected_count']==4
    assert len(preview['edges'])==12 and preview['dry_run']


@pytest.mark.parametrize('operation',['fillet','chamfer'])
def test_selective_finishing(live,operation):
    def populate(b):
        b.box('block',0,40,0,30,0,25)
        getattr(b,operation)('block',2,edges_rule={'axis':'y'})
    _,result,measured=build_measured(live,operation+'_four_edges',populate)
    assert 'selected_edges=4' in result.log
    assert result.features_ok==2 and measured['volume_mm3']<40*30*25


def test_batch_and_failure_return_document_count_to_baseline(live):
    sw,out=live
    before=document_inventory(sw)
    records=[]
    for i in range(3):
        path=out/f'batch_{i}_{uuid.uuid4().hex[:6]}.SLDPRT'
        b=PartBuilder(str(path)).cylinder('shaft',r=6,h=25)
        result=b.build(keep_open=False)
        assert result.ok,result.error
        after=document_inventory(sw)
        assert after['document_count']==before['document_count']
        records.append({'ok':result.ok,'log':result.log,'resources':after})
    path=out/f'failed_{uuid.uuid4().hex[:6]}.SLDPRT'
    b=PartBuilder(str(path)).box('bad',0,20,0,20,0,20).fillet('bad',1000)
    result=b.build()
    assert not result.ok and not path.exists()
    assert document_inventory(sw)['document_count']==before['document_count']
    records.append({'expected_failure':True,'log':result.log,'resources':document_inventory(sw)})
    (out/'batch_resource_verification.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')


def test_budget_rejection_does_not_create_document(live):
    sw,out=live
    count=document_inventory(sw)['document_count']
    path=out/f'budget_{uuid.uuid4().hex[:6]}.SLDPRT'
    result=PartBuilder(str(path)).box('block',0,10,0,10,0,10).build(max_documents=count)
    assert not result.ok and not path.exists()
    assert '上限' in result.log and document_inventory(sw)['document_count']==count


def test_native_pdf_and_truthful_delivery_check(live):
    sw,out=live
    _,result,_=build_measured(live,'pdf_block',lambda b:b.box('block',0,40,0,20,0,30))
    target=out/f'native_{uuid.uuid4().hex[:6]}.SLDDRW'
    made=drawing.produce(result.path,str(target))
    assert made['ok'] and not made['annotations_requested'] and not made['ready_for_manufacture']
    layout=drawing.normalize_layout(str(target))
    assert layout['ok'],layout
    exported=drawing.export_pdf(str(target))
    assert exported['ok'] and exported['sw_reported_ok'] and exported['err']==0,exported
    assert exported['validation']['page_count']==1 and exported['validation']['all_pages_rendered']
    review=drawing.delivery_check(str(target))
    assert review['ok'] and review['ready_for_manufacture'] is False,review
    (out/'native_pdf_verification.json').write_text(json.dumps({'made':made,'layout':layout,
        'export':exported,'review':review},ensure_ascii=False,indent=2),encoding='utf-8')
