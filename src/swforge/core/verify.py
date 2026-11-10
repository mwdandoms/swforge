def explicit_readback(result):
    """Only explicit verification, not a generic ok flag, establishes task success."""
    return isinstance(result, dict) and result.get('ok') is True and result.get('task_verified') is True
