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
        sim = Python("BoonCore simulator\n(S1, synthetic)")
        agents = Lambda("Agent API\n(S7, own telemetry)")
        exports = CostAndUsageReport("AWS Data Exports\n(S2/S7, FOCUS 1.2)")

    with Cluster("Short-lived operations data"):
        logs = CloudwatchLogs("CloudWatch Logs\n(7 days, run_id)")
        xray = XRay("X-Ray")
        alarms = Cloudwatch("≤ 10 alarms")
        sns = SNS("SNS alerts")

    compact = Lambda("Nightly compaction")

    with Cluster("S3 (long-term)"):
        tel = S3("telemetry/\n(Parquet)")
        bronze = S3("bronze/")

    sim >> Edge(label="gen_ai.* + mc.* attributes") >> bronze
    agents >> Edge(label="structured logs") >> logs
    agents >> Edge(label="traces", style="dotted") >> xray
    logs >> Edge(label="metric filters") >> alarms
    alarms >> Edge(label="notify") >> sns
    logs >> Edge(label="export") >> compact
    compact >> Edge(label="write") >> tel
    tel >> Edge(label="dogfood tenant") >> bronze
    exports >> Edge(label="daily Parquet") >> bronze
