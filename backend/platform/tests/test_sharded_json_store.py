from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.platform.non_structured import ShardedJSONStore


class ShardedJSONStoreTest(unittest.TestCase):
    def test_shards_indexes_reads_and_rebuilds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ShardedJSONStore(directory, max_shard_bytes=1_024, max_documents=2)
            now = datetime(2026, 8, 13, tzinfo=timezone.utc)
            for index in range(5):
                store.append(tenant_id="tenant:a", content_type="memory", topic="weekly", document_id=f"doc-{index}", content={"text": "x" * 40}, tags=["weekly"], now=now)
            month = Path(directory) / "tenant_a" / "memory" / "weekly" / "2026" / "08"
            self.assertEqual(len(list(month.glob("shard-*.json"))), 3)
            self.assertEqual(store.get(tenant_id="tenant:a", content_type="memory", topic="weekly", document_id="doc-3", year="2026", month="08")["content"]["text"], "x" * 40)
            (month / "index.json").unlink()
            rebuilt = store.rebuild_index(month)
            self.assertEqual(len(rebuilt["documents"]), 5)
            topic_index = json.loads((Path(directory) / "tenant_a" / "topic-index" / "memory.json").read_text(encoding="utf-8"))
            month_entry = next(iter(topic_index["topics"]["weekly"].values()))
            self.assertEqual(month_entry["index_checksum"], rebuilt["checksum"])

    def test_duplicate_path_escape_and_index_tamper_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ShardedJSONStore(directory, max_shard_bytes=2_048, max_documents=10)
            now = datetime(2026, 8, 13, tzinfo=timezone.utc)
            store.append(tenant_id="tenant", content_type="knowledge", topic="metric", document_id="doc", content={"x": 1}, now=now)
            with self.assertRaisesRegex(ValueError, "document_exists"):
                store.append(tenant_id="tenant", content_type="knowledge", topic="metric", document_id="doc", content={"x": 2}, now=now)
            with self.assertRaisesRegex(ValueError, "segment_invalid"):
                store.get(tenant_id="../escape", content_type="knowledge", topic="metric", document_id="doc")
            index_path = Path(directory) / "tenant" / "knowledge" / "metric" / "2026" / "08" / "index.json"
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            payload["version"] += 1
            index_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "checksum_mismatch"):
                store.get(tenant_id="tenant", content_type="knowledge", topic="metric", document_id="doc", year="2026", month="08")


if __name__ == "__main__":
    unittest.main()
