from __future__ import annotations

import io
import unittest

from backend.platform.ingestion import S3ArtifactObjectStore


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.put_count = 0

    def head_bucket(self, **kwargs):
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def head_object(self, *, Bucket: str, Key: str):
        try:
            value = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise KeyError("NotFound") from exc
        return {"Metadata": value["Metadata"], "ContentLength": len(value["Body"])}

    def put_object(self, **kwargs):
        self.put_count += 1
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = dict(kwargs)

    def get_object(self, *, Bucket: str, Key: str):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)]["Body"])}


class ArtifactObjectStoreTest(unittest.TestCase):
    def test_s3_adapter_is_tenant_scoped_idempotent_encrypted_and_hash_verified(self) -> None:
        client = _FakeS3Client()
        store = S3ArtifactObjectStore(
            "platform-artifacts", region="cn-east-1", prefix="prod", client=client
        )
        first = store.put("tenant_a", b"verified-content", ".csv")
        second = store.put("tenant_a", b"verified-content", ".csv")
        self.assertEqual(first, second)
        self.assertEqual(client.put_count, 1)
        stored = next(iter(client.objects.values()))
        self.assertEqual(stored["ServerSideEncryption"], "AES256")
        self.assertEqual(stored["Metadata"]["sha256"], first.content_hash)
        self.assertEqual(store.read("tenant_a", first.object_uri, first.content_hash), b"verified-content")
        with self.assertRaises(PermissionError):
            store.read("tenant_b", first.object_uri, first.content_hash)
        with self.assertRaises(RuntimeError):
            store.read("tenant_a", first.object_uri, "0" * 64)
        self.assertTrue(store.health()["ready"])


if __name__ == "__main__":
    unittest.main()
