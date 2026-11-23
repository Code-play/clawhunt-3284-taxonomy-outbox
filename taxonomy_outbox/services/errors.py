"""Domain errors raised by the taxonomy service and mapped to HTTP errors by the API."""

from __future__ import annotations


class TaxonomyError(Exception):
    """Base class for expected domain failures."""


class TagNotFound(TaxonomyError):
    """The tag does not exist in the caller's tenant scope."""


class DictionaryNotFound(TaxonomyError):
    """The dictionary does not exist in the caller's tenant scope."""


class InvalidTagTransition(TaxonomyError):
    """The requested lifecycle transition is not allowed from the current state."""


class TagVersionConflict(TaxonomyError):
    """The caller's expected version does not match the stored tag version."""


class InvalidMerge(TaxonomyError):
    """The merge source/target combination is not allowed."""


class DuplicateTagCode(TaxonomyError):
    """A live tag with the same code already exists in the dictionary."""
