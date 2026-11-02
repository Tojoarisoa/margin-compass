"""Retrieval (ADR-008): S3 Vectors with tenant filters, fused with an in-Lambda BM25 index."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.ml import Bedrock
from diagrams.aws.storage import S3

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("retrieval", "Retrieval (ADR-008)")):
    corpus = S3("knowledge/ corpus\npolicies, contracts,\nplaybooks, cards")

    with Cluster("Embed stage (only when the corpus changed)"):
        embed = Lambda("Parse, chunk,\nhash, metadata")
        titan = Bedrock("Titan Text\nEmbeddings V2\n(512 dims)")

    with Cluster("Indexes"):
        vectors = S3("S3 Vectors index\nfilters: tenant_id,\nclause_type, effective_date")
        bm25 = S3("rag/ BM25 index file")

    with Cluster("Query time"):
        agent = Lambda("AG-07 Contract &\nPolicy Advisor")
        fuse = Lambda("Hybrid fusion\n(vector + BM25)")

    corpus >> embed >> titan >> Edge(label="upsert") >> vectors
    embed >> bm25
    agent >> Edge(label="query + tenant filter") >> vectors
    agent >> Edge(label="load in Lambda") >> bm25
    [vectors, bm25] >> fuse >> Edge(label="cited chunks") >> agent
