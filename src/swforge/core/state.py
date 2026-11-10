from dataclasses import dataclass, field, asdict
import time
import uuid


@dataclass
class Execution:
    operation: str
    arguments: dict
    document_path: str = ''
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: str = 'not_started'
    tool_success: bool = False
    task_verified: bool = False
    retry_allowed: bool = True
    trace: list = field(default_factory=list)

    def event(self, kind, **data):
        self.trace.append(dict(sequence=len(self.trace), time_ns=time.time_ns(), kind=kind, **data))

    def as_dict(self):
        return asdict(self)


def execute(record, function, verify=None):
    """One attempt only. Unknown operations cannot be retried by this record."""
    if record.state != 'not_started':
        raise RuntimeError('Execution already attempted; unknown states require manual reconciliation')
    record.state = 'running'
    record.event('started')
    try:
        result = function()
        record.event('returned')
        uncertain = isinstance(result, dict) and (result.get('mutation_state') == 'unknown' or result.get('state') == 'unknown')
        if uncertain:
            record.state = 'unknown'
            record.retry_allowed = False
        else:
            record.tool_success = not isinstance(result, dict) or result.get('ok') is True
            record.task_verified = bool(record.tool_success and verify is not None and verify(result))
            record.state = 'succeeded' if record.tool_success and record.task_verified else 'failed'
        record.event('finished', state=record.state, task_verified=record.task_verified)
        return result
    except (TimeoutError, ConnectionError) as exc:
        record.state = 'unknown'
        record.retry_allowed = False
        record.event('uncertain', error=str(exc))
        return dict(ok=False, error=str(exc), mutation_state='unknown')
    except Exception as exc:
        record.state = 'failed'
        record.event('failed', error=str(exc))
        return dict(ok=False, error=f'{type(exc).__name__}: {exc}')
