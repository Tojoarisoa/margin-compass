"""System overview (ADR-002). Everything runs in us-east-1; nothing is always on."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECR, Lambda
from diagrams.aws.cost import Budgets
from diagrams.aws.database import Dynamodb
from diagrams.aws.devtools import XRay
from diagrams.aws.integration import SNS, SQS, EventbridgeScheduler, StepFunctions
from diagrams.aws.management import Cloudwatch, SystemsManagerParameterStore
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import CloudFront
from diagrams.aws.security import IAM, Cognito
from diagrams.aws.storage import S3
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import Users

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("overview", "Margin Compass: system overview (us-east-1)")):
    users = Users("Reviewers\n& owner")
    ci = GithubActions("GitHub Actions\n(CDK deploy)")

    with Cluster("AWS account (Paid plan) — us-east-1"):
        oidc = IAM("OIDC deploy role")
        cdn = CloudFront("CloudFront\n(single domain, OAC)")
        cognito = Cognito("Cognito\n(owner mode, Target)")

        with Cluster("Serving"):
            site = S3("S3 site/ +\npublish/")
            api = Lambda("Agent API\n(LangGraph, LWA)")

        with Cluster("Nightly pipeline"):
            sched = EventbridgeScheduler("EventBridge\nScheduler")
            sfn = StepFunctions("Step Functions\nStandard")
            jobs = Lambda("Data/ML jobs\n(DuckDB + dbt)")
            images = ECR("ECR\n(2 images)")

        with Cluster("Data & state"):
            lake = S3("S3 lake\nbronze/silver/gold")
            vectors = S3("S3 Vectors\n+ BM25 file")
            ddb = Dynamodb("DynamoDB\n(provisioned ≤ 25 RCU/WCU)")

        bedrock = Bedrock("Bedrock\n(Nova Micro, Haiku,\nTitan Embeddings)")

        with Cluster("Operate & govern"):
            cw = Cloudwatch("CloudWatch logs\n+ ≤ 10 alarms")
            xray = XRay("X-Ray\n(traces)")
            budgets = Budgets("Budgets + kill switch\n(IAM deny, red dashed)")
            ssm = SystemsManagerParameterStore("SSM Parameter Store\n(config, no secrets in repo)")
            dlq = SQS("SQS DLQ")
            alerts = SNS("SNS alerts")

    users >> cdn
    cdn >> site
    cdn >> Edge(label="/api (OAC)") >> api
    users >> Edge(style="dashed", label="owner sign-in") >> cognito
    ci >> Edge(label="OIDC, no keys") >> oidc

    sched >> sfn >> jobs
    images - Edge(style="dotted") - jobs
    jobs >> lake
    jobs >> Edge(label="publish") >> site
    jobs >> vectors
    jobs >> Edge(style="dashed", label="failures") >> dlq

    api >> bedrock
    jobs >> bedrock
    api >> vectors
    api >> lake
    api >> ddb

    api >> Edge(style="dotted") >> cw
    cw >> alerts
    budgets >> Edge(style="dashed", color="#c62828") >> api
