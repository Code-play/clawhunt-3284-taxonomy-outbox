"""Service layer: tag lifecycle operations and the outbox writer."""

from .errors import (
    DictionaryNotFound,
    DuplicateTagCode,
    InvalidMerge,
    InvalidTagTransition,
    TagNotFound,
    TagVersionConflict,
    TaxonomyError,
)
from .outbox_service import OutboxWriter
from .taxonomy_service import MutationResult, TaxonomyService, UPDATABLE_TAG_FIELDS

__all__ = [
    "DictionaryNotFound",
    "DuplicateTagCode",
    "InvalidMerge",
    "InvalidTagTransition",
    "TagNotFound",
    "TagVersionConflict",
    "TaxonomyError",
    "OutboxWriter",
    "MutationResult",
    "TaxonomyService",
    "UPDATABLE_TAG_FIELDS",
]
