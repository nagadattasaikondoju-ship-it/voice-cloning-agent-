class PermanentError(RuntimeError):
    """A provider error that retrying will not fix (bad key, no balance, plan limits)."""
