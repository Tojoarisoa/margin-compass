"""Nightly pipeline (ADR-004): DuckDB + dbt in Lambda container images."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECR, Lambda
from diagrams.aws.integration import SQS, EventbridgeScheduler, StepFunctions
from diagrams.aws.storage import S3
from diagrams.onprem.analytics import Dbt
from diagrams.onprem.database import Duckdb

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("pipeline", "Nightly pipeline (ADR-004)")):
    sched = EventbridgeScheduler("EventBridge Scheduler\n(nightly; off in dev)")
    sfn = StepFunctions("Step Functions Standard\n(~15 transitions/run)")
    images = ECR("ECR: data/ML image\n(DuckDB, dbt, extensions bundled)")

    with Cluster("Lambda container jobs (≤ 15 min, ≤ 6 GB)"):
        ingest = Lambda("1 Ingest")
        transform = Lambda("2 Transform\ndbt-duckdb")
        validate = Lambda("3 Validate\ncontracts, preservation")
        train = Lambda("4 Train\n(weekly or drift)")
        embed = Lambda("5 Embed\n(if corpus changed)")
        review = Lambda("6 Nightly margin\nreview graph")
        evaluate = Lambda("7 Evaluate")
        publish = Lambda("8 Publish")

    with Cluster("S3 lake (one bucket, prefixes)"):
        bronze = S3("bronze/")
        silver = S3("silver/")
        gold = S3("gold/ (≤ 300 MB)")
        quarantine = S3("quarantine/")
        snapshots = S3("publish/")

    dlq = SQS("SQS DLQ")
    dbt = Dbt("dbt models\n+ tests")
    duck = Duckdb("DuckDB\n(in Lambda)")

    sched >> sfn >> ingest
    ingest >> transform >> validate >> train >> embed >> review >> evaluate >> publish
    images - Edge(style="dotted", label="image") - transform

    ingest >> bronze
    transform >> Edge(label="httpfs, credential chain") >> silver
    silver >> gold
    validate >> Edge(style="dashed", label="error: quarantine") >> quarantine
    publish >> snapshots
    sfn >> Edge(style="dashed", label="failures") >> dlq
    transform - Edge(style="dotted") - dbt
    transform - Edge(style="dotted") - duck
