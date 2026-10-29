"""On-disk codecs, one module per format version.

Every codec module provides:

``VERSION``                       the version number it handles
``encode(table, metadata)``       -> bytes  (raises NotRepresentableError)
``check_representable(table, metadata)``
``decode(data)``                  -> DecodedArchive
``describe(data)``                -> dict of structural facts for ``info``

and the reader/writer in :mod:`tsarc.archive` dispatch on the version found
in (or requested for) a file.
"""
from dataclasses import dataclass, field

from ..errors import UnsupportedVersionError
from . import v1, v2

CODECS = {v1.VERSION: v1, v2.VERSION: v2}

LATEST_VERSION = max(CODECS)
DEFAULT_WRITE_VERSION = 2


def codec_for(version):
    try:
        return CODECS[version]
    except KeyError:
        raise UnsupportedVersionError(version) from None


def known_versions():
    return sorted(CODECS)


@dataclass
class DecodedArchive:
    """What a codec's ``decode`` returns."""

    version: int
    table: object
    metadata: dict = field(default_factory=dict)
