"""Regressions for resource ownership, edge rules and export evidence."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import pytest

from swforge import drawing,modeling,resources


@pytest.mark.parametrize('rule',[{'axis':'q'},{'min_length_mm':0},{'max_length_mm':float('nan')},
                                  {'min_length_mm':10,'max_length_mm':2},{'unknown':1}])
def test_invalid_edge_rule_is_rejected_before_mutation(tmp_path,rule):
    b=modeling.PartBuilder(str(tmp_path/'p.SLDPRT')).box('block',0,40,0,30,0,25)
    with pytest.raises(ValueError):
        b.fillet('block',2,edges_rule=rule)
    assert b.feature_count==1


def test_codegen_cleanup_and_budget(tmp_path):
    b=modeling.PartBuilder(str(tmp_path/'p.SLDPRT')).box('block',0,40,0,30,0,25)
    b.chamfer('block',2,edges_rule={'axis':'y'})
    src=b.render_cs(keep_open=False,max_documents=4)
    assert 'before>=4' in src
    assert '(!saved || !false)' in src
    assert 'selected_edges=' in src
    assert '"y",-1.0,-1.0' in src


def test_pdf_parser_rejects_header_only(tmp_path):
    path=tmp_path/'bad.pdf';path.write_bytes(b'%PDF-1.7\nnot a PDF')
    assert not drawing._validate_pdf(str(path),1)['ok']


def test_document_scope_never_closes_preexisting_modified_doc(tmp_path,monkeypatch):
    path=str(tmp_path/'out.SLDDRW')
    prior={'path':path,'title':'prior','modified':True}
    fresh={'path':str(tmp_path/'new.SLDDRW'),'title':'fresh','modified':False}
    inventories=iter([{'document_count':1,'documents':[prior]},
                      {'document_count':2,'documents':[prior,fresh]},
                      {'document_count':2,'documents':[prior,fresh]},
                      {'document_count':1,'documents':[prior]}])
    closed=[];sw=SimpleNamespace(CloseDoc=closed.append)
    monkeypatch.setattr(resources,'get_session',lambda:SimpleNamespace(sw=lambda:sw))
    monkeypatch.setattr(resources,'document_inventory',lambda sw:next(inventories))
    with resources.document_scope(path,keep_open=False,related_paths=[fresh['path']]):
        pass
    assert closed==[fresh['path']]


def test_document_budget_reserves_source_model(tmp_path,monkeypatch):
    monkeypatch.setattr(resources,'get_session',lambda:SimpleNamespace(sw=lambda:object()))
    monkeypatch.setattr(resources,'document_inventory',lambda sw:{'document_count':7,'documents':[]})
    with pytest.raises(Exception,match='上限'):
        with resources.document_scope(str(tmp_path/'out.SLDDRW'),related_paths=[str(tmp_path/'model.SLDPRT')]):
            pytest.fail('must reject before creating a drawing and model')


def test_produce_defaults_to_views_and_requires_review(tmp_path,monkeypatch):
    lease=SimpleNamespace(failed=False)
    monkeypatch.setattr(resources,'document_scope',lambda *a,**k:nullcontext(lease))
    calls=[]
    def produce(*a,**k):
        calls.append(k);return {'ok':True}
    monkeypatch.setattr(drawing,'_produce',produce)
    result=drawing.produce(str(tmp_path/'p.SLDPRT'))
    assert calls[0]['annotations'] is False
    assert result['ready_for_manufacture'] is False and result['review_required']
