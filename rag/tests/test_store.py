import numpy as np
import pytest
from botocore.stub import Stubber
import boto3

from mc_rag.store import LocalVectorStore, S3VectorsStore, VectorRecord, matches

META = {"tenant_id": "bc-t0003", "clause_type": "sla", "tags": ["a", "b"]}


@pytest.mark.parametrize("flt, expected", [
    ({"tenant_id": "bc-t0003"}, True),
    ({"tenant_id": {"$eq": "bc-t0009"}}, False),
    ({"tenant_id": {"$in": ["bc-t0003", "all"]}}, True),
    ({"tenant_id": {"$in": ["bc-t0009", "all"]}}, False),
    ({"tenant_id": {"$nin": ["bc-t0003"]}}, False),
    ({"tenant_id": {"$ne": "bc-t0009"}}, True),
    ({"missing": {"$exists": False}}, True),
    ({"tags": {"$eq": "b"}}, True),
    ({"$and": [{"tenant_id": "bc-t0003"}, {"clause_type": {"$in": ["sla"]}}]}, True),
    ({"$or": [{"tenant_id": "bc-t0009"}, {"clause_type": "pricing"}]}, False),
])
def test_filter_semantics(flt, expected):
    assert matches(META, flt) is expected


def test_non_filterable_keys_are_rejected():
    with pytest.raises(ValueError, match="non-filterable"):
        matches({"text": "x"}, {"text": "x"})


def test_local_store_round_trip(tmp_path):
    path = tmp_path / "index.json"
    s = LocalVectorStore(4, path)
    s.put([VectorRecord("k1", np.array([1, 0, 0, 0], np.float32), {"tenant_id": "all", "content_sha": "h1"})])
    s2 = LocalVectorStore(4, path)
    assert s2.get_hashes(["k1", "nope"]) == {"k1": "h1"}
    assert s2.query(np.array([1, 0, 0, 0]), 5, {"tenant_id": "all"})[0].distance == pytest.approx(0.0, abs=1e-6)
    with pytest.raises(ValueError, match="dim"):
        LocalVectorStore(8, path)


def test_s3vectors_request_shapes():
    client = boto3.client("s3vectors", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    store = S3VectorsStore("mc-dev-knowledge", "kb-titan-v2-512", client=client)
    flt = {"tenant_id": {"$in": ["bc-t0003", "all"]}}
    base = {"vectorBucketName": "mc-dev-knowledge", "indexName": "kb-titan-v2-512"}
    with Stubber(client) as stub:
        stub.add_response("get_vectors", {"vectors": [{"key": "k1", "metadata": {"content_sha": "h1"}}]},
                          {**base, "keys": ["k1"], "returnData": False, "returnMetadata": True})
        stub.add_response("put_vectors", {}, {**base, "vectors": [
            {"key": "k1", "data": {"float32": [1.0, 0.0]}, "metadata": {"tenant_id": "all"}}]})
        stub.add_response("query_vectors", {"vectors": [{"key": "k1", "distance": 0.25, "metadata": {"tenant_id": "all"}}],
                                            "distanceMetric": "cosine"},
                          {**base, "topK": 3, "queryVector": {"float32": [1.0, 0.0]}, "filter": flt,
                           "returnMetadata": True, "returnDistance": True})
        stub.add_response("list_vectors", {"vectors": [{"key": "k2"}], "nextToken": "t"}, base)
        stub.add_response("list_vectors", {"vectors": [{"key": "k1"}]}, {**base, "nextToken": "t"})
        stub.add_response("delete_vectors", {}, {**base, "keys": ["k2"]})
        assert store.get_hashes(["k1"]) == {"k1": "h1"}
        store.put([VectorRecord("k1", np.array([1.0, 0.0], np.float32), {"tenant_id": "all"})])
        assert store.query(np.array([1.0, 0.0]), 3, flt)[0].distance == 0.25
        assert store.keys() == ["k1", "k2"]
        store.delete(["k2"])
        stub.assert_no_pending_responses()
