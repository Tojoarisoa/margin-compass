"""Dashboard data path (ADR-009): static SPA, JSON snapshots, lazy DuckDB-WASM, same origin."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.network import CloudFront
from diagrams.aws.storage import S3
from diagrams.onprem.client import Client

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("dashboard", "Dashboard data path (ADR-009)")):
    publish = Lambda("8 Publish step")

    with Cluster("S3 (one origin behind CloudFront)"):
        site = S3("site/\nSPA + self-hosted\nDuckDB-WASM bundles\n(pinned version)")
        kpi = S3("publish/ KPI JSON\n(≤ 200 KB per page)")
        parquet = S3("publish/ Parquet\n(≤ 5 MB per page)")

    cdn = CloudFront("CloudFront\n(same origin: no CORS)")
    browser = Client("Browser\nSPA + DuckDB-WASM\n(lazy, exploration pages)")

    publish >> [kpi, parquet]
    [site, kpi, parquet] >> cdn
    cdn >> Edge(label="app + JSON") >> browser
    cdn >> Edge(label="Parquet range reads\n(spike M1-07)", style="dashed") >> browser
