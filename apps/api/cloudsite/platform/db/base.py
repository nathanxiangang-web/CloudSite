from sqlalchemy.orm import DeclarativeBase

from ...database import StateBase as _LegacyStateBase, IndexBase as _LegacyIndexBase

StateBase = _LegacyStateBase
IndexBase = _LegacyIndexBase

__all__ = ['StateBase', 'IndexBase']
