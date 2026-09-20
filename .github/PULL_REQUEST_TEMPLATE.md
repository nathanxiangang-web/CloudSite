## Summary

One or two sentences describing what this PR changes and why.

## Changes

- 
- 

## Testing

- [ ] New tests added or existing tests updated
- [ ] `python -m pytest -q` passes locally
- [ ] No schema version assertion failures
- [ ] No new secrets or credentials in code/config

## Migration notes

If this PR adds a schema migration, state the new `CURRENT_SCHEMA_VERSION` and confirm that existing test assertions have been updated.

## Checklist

- [ ] Code follows existing conventions (pure application services, domain exceptions, Result dataclass)
- [ ] No comments added unless explicitly requested
- [ ] Router registration added to `main.py` if new route file
- [ ] ORM model added to `models.py` if new table