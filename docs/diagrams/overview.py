"""System overview (ADR-002). Everything runs in us-east-1; nothing is always on.

Operations and cost governance are drawn separately in governance.py to keep this readable.
Rule for every diagram here: each node has at least one labeled connection.
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECR, Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import SQS, EventbridgeScheduler, StepFunctions
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import CloudFront
from diagrams.aws.security import IAM, Cognito
from diagrams.aws.storage import S3
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import Users

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("overview", "Margin Compass: system overview (us-east-1)")):
    users = Users("Reviewers & owner")
    ci = GithubActions("GitHub Actions")

    with Cluster("AWS account (Paid plan), us-east-1"):
        with Cluster("Deploy"):
            oidc = IAM("OIDC deploy role\n(no access keys)")
            images = ECR("ECR (2 images)")

        with Cluster("Edge"):
            cdn = CloudFront("CloudFront\n(one domain, OAC)")
            cognito = Cognito("Cognito\n(owner mode)")

        with Cluster("Serving"):
            site = S3("S3 site/ + publish/")
            api = Lambda("Agent API\n(LangGraph)")

        with Cluster("Nightly pipeline"):
            sched = EventbridgeScheduler("Scheduler")
            sfn = StepFunctions("Step Functions")
            jobs = Lambda("Data/ML jobs\n(DuckDB + dbt)")
            dlq = SQS("DLQ")

        with Cluster("Data & models"):
            lake = S3("S3 lake\nbronze/silver/gold")
            vectors = S3("S3 Vectors\n+ BM25 file")
            ddb = Dynamodb("DynamoDB\n(≤ 25 RCU/WCU)")
            bedrock = Bedrock("Bedrock")

    # Deploy path
    ci >> Edge(label="assume role (OIDC)") >> oidc
    oidc >> Edge(label="push images") >> images
    images >> Edge(label="image") >> jobs
    images >> Edge(label="image") >> api

    # Request path
    users >> Edge(label="HTTPS") >> cdn
    users >> Edge(label="owner sign-in", style="dashed") >> cognito
    cdn >> Edge(label="pages, snapshots") >> site
    cdn >> Edge(label="/api") >> api
    cognito >> Edge(label="owner token", style="dashed") >> api

    # Nightly pipeline
    sched >> Edge(label="nightly") >> sfn
    sfn >> Edge(label="runs") >> jobs
    sfn >> Edge(label="failures", style="dashed") >> dlq
    jobs >> Edge(label="read / write") >> lake
    jobs >> Edge(label="embed") >> vectors
    jobs >> Edge(label="embeddings") >> bedrock
    jobs >> Edge(label="publish") >> site

    # Agent dependencies
    api >> Edge(label="query gold") >> lake
    api >> Edge(label="retrieve") >> vectors
    api >> Edge(label="state, limits") >> ddb
    api >> Edge(label="invoke models") >> bedrock
