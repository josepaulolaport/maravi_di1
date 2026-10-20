"""The processing module's one internal error."""

from __future__ import annotations


class ProcessingError(RuntimeError):
    """The facts do not allow computing a date: a technical failure of the chain, never user
    input (e.g. a processed D−1 with no published rows, or a traded asset that does not exist).
    The run turns it into the chain's failure on the date (``PROCESSING_ERROR``)."""
