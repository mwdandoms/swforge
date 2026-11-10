from contextvars import ContextVar

CURRENT_EXECUTION = ContextVar('swforge_execution', default=None)


def event(kind, **data):
    record = CURRENT_EXECUTION.get()
    if record is not None:
        record.event(kind, **data)
