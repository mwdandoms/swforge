"""Explicit confirmation, single use, TTL, file and active-document CAS."""
from pathlib import Path
import hashlib
import json
import time
import uuid
import sqlite3
from ..variants import file_sha256


def fingerprint(name, args):
    return hashlib.sha256(json.dumps([name,args],sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def preview_operation(name,args,document_path,before,after,*,active_path,switch_count):
    path=str(Path(document_path).resolve())
    if Path(active_path).resolve() != Path(path):
        raise ValueError('Preview must refer to the active saved document')
    preview=dict(operation=name,arguments=args,document_path=path,document_revision=file_sha256(path),
                 operation_fingerprint=fingerprint(name,args),before=before,after=after,switch_count=switch_count)
    preview['preview_hash']=fingerprint('preview',preview)
    return preview


class ApprovalStore:
    def __init__(self, clock=time.time, database=None):
        self.clock=clock
        self.db=sqlite3.connect(database or ':memory:',check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.commit()

    def issue(self,preview,*,confirmed=False,ttl_s=300):
        if confirmed is not True:
            raise ValueError('A preview is not authorization; explicit confirmation is required')
        if not 0 < ttl_s <= 300:
            raise ValueError('TTL must be 1..300 seconds')
        original=dict(preview);digest=original.pop('preview_hash')
        if fingerprint('preview',original)!=digest:
            raise ValueError('Preview was modified')
        if file_sha256(preview['document_path']) != preview['document_revision']:
            raise ValueError('Document changed since preview')
        token=str(uuid.uuid4())
        record=dict(preview,issued_at=self.clock(),ttl_s=ttl_s,single_use=True)
        with self.db:
            self.db.execute('INSERT INTO tokens VALUES (?,?)',(token,json.dumps(record,ensure_ascii=False)))
        return dict(record,token=token)

    def consume(self,token,name,args,*,active_path,switch_count):
        # IMMEDIATE serializes single-use consumption across CLI/server processes.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            found=self.db.execute('SELECT payload FROM tokens WHERE token=?',(token,)).fetchone()
            self.db.execute('DELETE FROM tokens WHERE token=?',(token,))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        if not found:
            raise ValueError('Unknown or used token')
        record=json.loads(found[0])
        if self.clock() >= record['issued_at']+record['ttl_s']:
            raise ValueError('Expired token')
        if record['operation_fingerprint']!=fingerprint(name,args):
            raise ValueError('Operation or arguments changed')
        if Path(active_path).resolve()!=Path(record['document_path']) or switch_count!=record['switch_count']:
            raise ValueError('Active document switched')
        if file_sha256(record['document_path'])!=record['document_revision']:
            raise ValueError('Document revision changed')
        return record
