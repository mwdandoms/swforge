"""Native capabilities by tested SolidWorks release."""
import json
from pathlib import Path


def load_matrix(path=None):
    data=json.loads(Path(path or Path(__file__).with_name('capabilities.yaml')).read_text(encoding='utf-8'))
    ids=set()
    for row in data['capabilities']:
        if row['id'] in ids or row['semantic'] not in ('exact','equivalent') or row['status'] not in ('verified','unverified','blocked'):
            raise ValueError('Invalid capability matrix')
        if row['status']=='verified' and not row.get('evidence'):
            raise ValueError('Verified capability requires evidence')
        ids.add(row['id'])
    return data


def capability(name, sw_version=None):
    row=next((dict(r) for r in load_matrix()['capabilities'] if r['id']==name),None)
    if row is None:
        return dict(id=name,status='unverified',semantic='exact',note='No acceptance claim')
    if sw_version is not None:
        version=str(sw_version)
        if version in row.get('blocked_versions',[]):
            row.update(status='blocked',reason=row.get('note','Explicitly blocked version'))
        elif version not in row.get('sw_versions',[]):
            row.update(status='unverified',reason='No native acceptance for this operation and SolidWorks release')
    return row


def host_status(connect=False):
    from .version import __version__
    data=load_matrix();version=None;error=None
    if connect:
        try:
            from .session import get_session,_value
            revision=str(_value(get_session().sw(),'RevisionNumber'))
            version=str(int(revision.split('.')[0])+1992)
        except Exception as exc:
            error=str(exc)
    rows=[capability(r['id'],version) for r in data['capabilities']]
    return dict(ok=True,version=__version__,sw_version=version,connection_error=error,
                capabilities_total=len(rows),verified=sum(r['status']=='verified' for r in rows),
                blocked=[r for r in rows if r['status']=='blocked'],degraded=[r for r in rows if r['semantic']=='equivalent'],
                cross_version=data['cross_version'],capabilities=rows)
