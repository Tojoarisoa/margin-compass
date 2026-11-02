"""Dashboard data path (ADR-009): static SPA, JSON snapshots, lazy DuckDB-WASM, same origin."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.network import CloudFront
from diagrams.aws.storage import S3
from diagrams.onprem.client import Client

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("dashboard", "Dashboard data path (ADR-009)")):
    publish = Lambda("8 Publish step")

    with Cluster("S3, one origin behind CloudFront"):
        site = S3("site/: SPA +\nself-hosted DuckDB-WASM\n(pinned version)")
        kpi = S3("publish/ KPI JSON\n(≤ 200 KB per page)")
        parquet = S3("publish/ Parquet\n(≤ 5 MB per page)")

    cdn = CloudFront("CloudFront\n(same origin: no CORS)")
    browser = Client("Browser\n(DuckDB-WASM loads\nlazily on exploration pages)")

    publish >> Edge(label="KPI snapshots") >> kpi
    publish >> Edge(label="exploration data") >> parquet
    site >> Edge(label="app bundle") >> cdn
    kpi >> Edge(label="JSON") >> cdn
    parquet >> Edge(label="Parquet") >> cdn
    cdn >> Edge(label="app + JSON") >> browser
    cdn >> Edge(label="Parquet range reads\n(spike M1-07)", style="dashed") >> browser
