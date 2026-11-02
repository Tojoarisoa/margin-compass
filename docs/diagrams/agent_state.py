"""Agent state (ADR-010, ADR-011): LangGraph checkpoints in provisioned DynamoDB with S3 offload."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.storage import S3

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("agent_state", "Agent state (ADR-010, ADR-011)")):
    graph = Lambda("Agent API\nLangGraph +\nDynamoDBSaver (pinned)")

    with Cluster("DynamoDB, provisioned, autoscaling off\n≤ 25 RCU / 25 WCU total incl. GSIs, dev + prod"):
        checkpoints = Dynamodb("checkpoints\n(TTL, gzip)")
        core = Dynamodb("core single table\nrate limits, budgets,\nactions, job status")

    offload = S3("S3 offload\n(checkpoints > 350 KB)")

    graph >> Edge(label="save / resume / HITL interrupt") >> checkpoints
    graph >> Edge(label="budget + rate-limit checks") >> core
    checkpoints >> Edge(style="dashed", label="large payloads") >> offload
