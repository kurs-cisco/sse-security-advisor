from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

try:
    from cbom_catalog.repository import (
        RETAINED_EMPTY_SERVICE_GROUPS_BY_COLLECTION,
        IngestStats,
        _read_stable_file,
        stats_as_dict,
    )
except ModuleNotFoundError as exc:
    if exc.name != "psycopg":
        raise
    IngestStats = None
    _read_stable_file = None
    stats_as_dict = None


@unittest.skipIf(IngestStats is None, "install project dependencies to run refresh tests")
class FingerprintRefreshTests(unittest.TestCase):
    def test_stable_file_read_returns_sha256_of_exact_bytes(self) -> None:
        payload = b'{"bomFormat":"CycloneDX","specVersion":"1.6"}\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_bytes(payload)
            content, stat, checksum = _read_stable_file(path)

        self.assertEqual(content, payload)
        self.assertEqual(stat.st_size, len(payload))
        self.assertEqual(checksum, hashlib.sha256(payload).hexdigest())

    def test_ingest_stats_exposes_unchanged_count(self) -> None:
        result = stats_as_dict(IngestStats(run_id=7, files_seen=3, files_unchanged=3))
        self.assertEqual(result["files_unchanged"], 3)
        self.assertEqual(result["files_loaded"], 0)

    def test_sse_collection_retains_approved_empty_coverage_groups(self) -> None:
        self.assertEqual(
            RETAINED_EMPTY_SERVICE_GROUPS_BY_COLLECTION["sse-cboms"],
            (
                "ANDROID-NO_CBOM",
                "IOS-NO_CBOM",
                "RSM-SECURE_CLIENT-NO_CBOM",
                "SWG-ROAMING-CLIENT-NO_CBOM",
            ),
        )


if __name__ == "__main__":
    unittest.main()
