"""Edge and request path (ADR-006, ADR-012): no VPC; CloudFront OAC to S3 and a Lambda URL."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.network import CloudFront
from diagrams.aws.storage import S3
from diagrams.onprem.client import Client

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("edge", "Edge and request path (ADR-006, ADR-012)")):
    browser = Client("Browser SPA\nhashes POST body\n(x-amz-content-sha256)")
    cdn = CloudFront("CloudFront\n(one distribution)")

    with Cluster("AWS: no VPC, so no NAT and no endpoints"):
        site = S3("S3 site/ + publish/\n(Block Public Access)")
        api = Lambda("Agent API function URL\nAWS_IAM, RESPONSE_STREAM,\nLambda Web Adapter")
        jobs = Dynamodb("DynamoDB core\n(job status)")

    browser >> Edge(label="GET pages, data") >> cdn
    browser >> Edge(label="POST /api/ask") >> cdn
    cdn >> Edge(label="OAC") >> site
    cdn >> Edge(label="OAC SigV4 request;\nstreamed response (spike M1-07)", forward=True, reverse=True) >> api
    api >> Edge(label="fallback: write job,\nclient polls status", style="dashed") >> jobs
