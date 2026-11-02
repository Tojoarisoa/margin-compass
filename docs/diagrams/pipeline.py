"""Nightly pipeline (ADR-004): DuckDB + dbt in Lambda container images."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECR, Lambda
from diagrams.aws.cost import CostAndUsageReport
from diagrams.aws.integration import SQS, EventbridgeScheduler, StepFunctions
from diagrams.aws.storage import S3
from diagrams.programming.language import Python

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("pipeline", "Nightly pipeline (ADR-004)")):
    with Cluster("Sources"):
        sim = Python("BoonCore simulator\n(S1–S6, synthetic)")
        exports = CostAndUsageReport("Data Exports\n(S7, FOCUS 1.2)")

    sched = EventbridgeScheduler("Scheduler\n(nightly; off in dev)")
    sfn = StepFunctions("Step Functions\nStandard")
    dlq = SQS("SQS DLQ")
    image = ECR("ECR image\nDuckDB + dbt,\nextensions bundled")

    with Cluster("Lambda container jobs (≤ 15 min, ≤ 6 GB), run in order"):
        ingest = Lambda("1 Ingest")
        transform = Lambda("2 Transform\n(dbt-duckdb)")
        validate = Lambda("3 Validate")
        train = Lambda("4 Train\n(weekly or drift)")
        embed = Lambda("5 Embed\n(if corpus changed)")
        review = Lambda("6 Margin review\ngraph")
        evaluate = Lambda("7 Evaluate")
        publish = Lambda("8 Publish")

    with Cluster("S3 lake (one bucket, prefixes)"):
        bronze = S3("bronze/")
        silver = S3("silver/")
        gold = S3("gold/\n(≤ 300 MB)")
        quarantine = S3("quarantine/")
        snapshots = S3("publish/")

    sched >> Edge(label="nightly") >> sfn
    sfn >> Edge(label="start") >> ingest
    sfn >> Edge(label="failures", style="dashed") >> dlq
    image >> Edge(label="all jobs") >> transform

    [sim, exports] >> Edge(label="raw files") >> ingest
    ingest >> transform >> validate >> train >> embed >> review >> evaluate >> publish

    ingest >> Edge(label="land") >> bronze
    transform >> Edge(label="conform") >> silver
    transform >> Edge(label="build marts") >> gold
    validate >> Edge(label="errors", style="dashed") >> quarantine
    publish >> Edge(label="snapshots") >> snapshots
