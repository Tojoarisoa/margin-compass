"""Operations and cost governance (ADR-002, PLAN.md §11, §14).

Three layers stop runaway spend, fastest first: code caps (per question, daily, monthly),
then alarms, then the AWS Budgets kill switch, which lags billing by up to a day (VER-06).
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.cost import Budgets, CostAndUsageReport, CostExplorer
from diagrams.aws.database import Dynamodb
from diagrams.aws.devtools import XRay
from diagrams.aws.integration import SNS
from diagrams.aws.management import Cloudwatch, SystemsManagerParameterStore
from diagrams.aws.storage import S3

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("governance", "Operations and cost governance (ADR-002)")):
    ssm = SystemsManagerParameterStore("SSM Parameter Store\n(config; no secrets in repo)")

    with Cluster("Workloads"):
        api = Lambda("Agent API")
        jobs = Lambda("Data/ML jobs")

    caps = Dynamodb("DynamoDB core\n(LLM budget counters)")

    with Cluster("Observe"):
        cw = Cloudwatch("CloudWatch\nlogs + ≤ 10 alarms")
        xray = XRay("X-Ray traces")

    with Cluster("Cost"):
        exports = CostAndUsageReport("Data Exports\n(FOCUS 1.2, daily)")
        anomaly = CostExplorer("Cost Anomaly\nDetection")
        budgets = Budgets("Budgets\n$3 alert, $5 kill switch")

    alerts = SNS("SNS alerts\n(owner email)")
    lake = S3("S3 lake\n(dogfood tenant S7)")

    ssm >> Edge(label="config", style="dotted") >> api
    ssm >> Edge(label="config", style="dotted") >> jobs
    api >> Edge(label="1st line: caps in code\n(≤ 8 calls/question, daily, monthly $)", headport="w") >> caps
    api >> Edge(label="logs") >> cw
    jobs >> Edge(label="logs") >> cw
    api >> Edge(label="traces", style="dotted") >> xray
    cw >> Edge(label="2nd line: alarms") >> alerts
    exports >> Edge(label="own bill") >> lake
    anomaly >> Edge(label="anomaly") >> alerts
    budgets >> Edge(label="threshold") >> alerts
    budgets >> Edge(label="3rd line: IAM deny\n(lags ≤ ~1 day)", color="#c62828", style="dashed") >> api
