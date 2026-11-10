def recover_owned(document_path, rollback, *, owns_baseline=False):
    """Never attempt blind rollback or replay after uncertain mutations."""
    from ..guard import verify_active
    if not owns_baseline or not verify_active(document_path, by='path'):
        return dict(ok=False, action='manual_reconciliation', reason='No owned active baseline')
    return dict(ok=bool(rollback()), action='owned_baseline_rollback')
