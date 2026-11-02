"""Retrieval (ADR-008): S3 Vectors with tenant filters, fused with an in-Lambda BM25 index."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.ml import Bedrock
from diagrams.aws.storage import S3

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("retrieval", "Retrieval (ADR-008)")):
    corpus = S3("knowledge/ corpus\n(policies, contracts,\nplaybooks, cards)")

    with Cluster("Embed stage (only when the corpus changed)"):
        embed = Lambda("Parse, chunk,\nhash, metadata")
        titan = Bedrock("Titan Embeddings V2\n(512 dims)")

    with Cluster("Indexes"):
        vectors = S3("S3 Vectors index\n(tenant_id, clause_type,\neffective_date filters)")
        bm25 = S3("rag/ BM25 index file")

    with Cluster("Query time (agent Lambda)"):
        agent = Lambda("AG-07 Contract &\nPolicy Advisor")
        tool = Lambda("Hybrid retrieval tool\n(vector + BM25 fusion)")

    corpus >> Edge(label="changed files") >> embed
    embed >> Edge(label="chunks") >> titan
    titan >> Edge(label="upsert vectors") >> vectors
    embed >> Edge(label="rebuild") >> bm25

    agent >> Edge(label="question + tenant_id;\ncited chunks back", forward=True, reverse=True) >> tool
    tool >> Edge(label="filtered vector query") >> vectors
    tool >> Edge(label="load index") >> bm25
