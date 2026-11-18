import json
import pytest
from swforge.core.state import Execution,execute
from swforge.core.approval import ApprovalStore,preview_operation
from swforge.core.ledger import capture_artifact,finalize_artifact,delivery_manifest


def test_tool_success_requires_independent_verification():
    r=Execution('test',{})
    execute(r,lambda:dict(ok=True))
    assert r.tool_success and not r.task_verified and r.state=='failed'


def test_readback_verified_task():
    r=Execution('test',{})
    assert execute(r,lambda:dict(ok=True,value=4),lambda x:x['value']==4)['ok']
    assert r.state=='succeeded'
    assert [e['sequence'] for e in r.trace]==list(range(len(r.trace)))


@pytest.mark.parametrize('error',[TimeoutError('timeout'),ConnectionError('lost host')])
def test_unknown_cannot_retry(error):
    r=Execution('test',{})
    def fail():raise error
    result=execute(r,fail)
    assert result['mutation_state']=='unknown' and not r.retry_allowed
    with pytest.raises(RuntimeError):execute(r,lambda:dict(ok=True))


def test_native_uncertain_return_is_unknown():
    r=Execution('native',{})
    execute(r,lambda:dict(ok=False,mutation_state='unknown'))
    assert r.state=='unknown' and not r.retry_allowed


def test_stale_and_unverified_block_delivery(tmp_path):
    p=tmp_path/'file';p.write_text('old')
    c=capture_artifact(p)
    row=finalize_artifact(c,tool_success=True,verified=True)
    assert row['produced_this_run'] is False
    assert delivery_manifest([row])['delivery']=='blocked'
    p.write_text('new')
    row=finalize_artifact(c,tool_success=True,verified=False)
    assert row['produced_this_run'] is None


def test_changed_after_verified_export_blocks_manifest(tmp_path):
    p=tmp_path/'file';c=capture_artifact(p);p.write_text('new')
    row=finalize_artifact(c,tool_success=True,verified=True)
    assert row['produced_this_run'] is True
    p.write_text('external edit')
    assert delivery_manifest([row])['delivery']=='blocked'


@pytest.fixture
def preview(tmp_path):
    p=tmp_path/'saved.SLDPRT';p.write_text('baseline')
    return preview_operation('purge',{'apply':True},str(p),{'bodies':2},{'bodies':1},active_path=str(p),switch_count=0)


def test_preview_has_no_token_and_needs_confirmation(preview):
    assert 'token' not in preview
    with pytest.raises(ValueError):ApprovalStore().issue(preview)


def test_one_use_across_process_stores(preview,tmp_path):
    database=str(tmp_path/'tokens.sqlite3')
    store=ApprovalStore(database=database);token=store.issue(preview,confirmed=True)['token']
    other=ApprovalStore(database=database)
    other.consume(token,'purge',{'apply':True},active_path=preview['document_path'],switch_count=0)
    with pytest.raises(ValueError):store.consume(token,'purge',{'apply':True},active_path=preview['document_path'],switch_count=0)


@pytest.mark.parametrize('change',['revision','active','switch','ttl','arguments'])
def test_cas_rejects_changed_context(preview,change):
    now=[0];store=ApprovalStore(clock=lambda:now[0]);token=store.issue(preview,confirmed=True)['token']
    path=preview['document_path'];count=0;args={'apply':True}
    if change=='revision':
        from pathlib import Path
        Path(path).write_text('changed')
    if change=='active':path=path+'.other'
    if change=='switch':count=1
    if change=='ttl':now[0]=301
    if change=='arguments':args={'apply':False}
    with pytest.raises(ValueError):store.consume(token,'purge',args,active_path=path,switch_count=count)


def test_modified_preview_rejected(preview):
    preview['after']={'bodies':0}
    with pytest.raises(ValueError):ApprovalStore().issue(preview,confirmed=True)
