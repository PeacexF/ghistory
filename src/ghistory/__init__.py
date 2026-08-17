"""ghistory — a daily historical snapshot of the GitHub ecosystem."""

__version__ = "0.1.0"

# Bumped only when the on-disk snapshot format changes in a way that makes older
# snapshots ambiguous. Stored in every snapshot alongside __version__.
SCHEMA_VERSION = 1
