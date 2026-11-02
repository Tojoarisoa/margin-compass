"""Telemetry and billing flow (ADR-007, ADR-015). Metadata and token counts only; no content."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.cost import CostAndUsageReport
from diagrams.aws.devtools import XRay
from diagrams.aws.integration import SNS
from diagrams.aws.management import Cloudwatch, CloudwatchLogs
from diagrams.aws.storage import S3
from diagrams.programming.language import Python

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("telemetry", "Telemetry and billing flow (ADR-007, ADR-015)")):
    with Cluster("Producers"):
        sim = Python("BoonCore simulator\nS1 synthetic telemetry")
        agents = Lambda("Agent API\nS7 own telemetry\n(gen_ai.* + mc.*)")
        exports = CostAndUsageReport("AWS Data Exports\nFOCUS 1.2, daily\n(S2 / S7 own bill)")

    logs = CloudwatchLogs("CloudWatch Logs\n(7-day retention,\nrun_id)")
    xray = XRay("X-Ray traces")
    alarms = Cloudwatch("≤ 10 alarms")
    sns = SNS("SNS alerts")

    compact = Lambda("Nightly compaction")
    with Cluster("S3"):
        tel = S3("telemetry/\n(Parquet)")
        bronze = S3("bronze/\n→ silver → gold")

    agents >> logs
    agents >> Edge(style="dotted") >> xray
    logs >> compact >> tel
    tel >> Edge(label="dogfood tenant") >> bronze
    sim >> Edge(label="OTel GenAI attributes") >> bronze
    exports >> Edge(label="Parquet") >> bronze
    logs >> alarms >> sns
