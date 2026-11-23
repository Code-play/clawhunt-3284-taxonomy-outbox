"""SQLAlchemy models of the taxonomy outbox service.

Importing this package registers every table on ``Base.metadata`` so Alembic
autogenerate and the test schema fixtures see the complete schema.
"""

from .base import Base, TimestampMixin, TenantMixin, UUIDPrimaryKeyMixin, utcnow
from .consumer import ConsumerDelivery
from .outbox import OutboxEvent, OutboxStatus
from .projections import MatchingTagProjection, SearchIndexDocument
from .taxonomy import DictionaryStatus, TagStatus, TaxonomyDictionary, TaxonomyTag

__all__ = [
    "Base",
    "TimestampMixin",
    "TenantMixin",
    "UUIDPrimaryKeyMixin",
    "utcnow",
    "ConsumerDelivery",
    "OutboxEvent",
    "OutboxStatus",
    "MatchingTagProjection",
    "SearchIndexDocument",
    "DictionaryStatus",
    "TagStatus",
    "TaxonomyDictionary",
    "TaxonomyTag",
]
