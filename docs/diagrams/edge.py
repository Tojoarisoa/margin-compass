"""Edge and request path (ADR-006, ADR-012): no VPC; CloudFront OAC to S3 and a Lambda URL."""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.network import CloudFront
from diagrams.aws.storage import S3
from diagrams.onprem.client import Client

from _style import diagram_kwargs

with Diagram(**diagram_kwargs("edge", "Edge and request path (ADR-006, ADR-012)")):
    browser = Client("Browser SPA\n(hashes POST body:\nx-amz-content-sha256)")
    cdn = CloudFront("CloudFront\n(one distribution)")

    with Cluster("AWS (no VPC: no NAT, no endpoints)"):
        site = S3("S3 site/ + publish/\n(OAC, Block Public Access)")
        with Cluster("Agent API"):
            api = Lambda("Function URL\nAuthType AWS_IAM\nRESPONSE_STREAM\n+ Lambda Web Adapter")
            jobs = Dynamodb("DynamoDB core\n(job status for polling)")

    browser >> Edge(label="GET /*") >> cdn
    browser >> Edge(label="POST /api/ask") >> cdn
    cdn >> Edge(label="OAC") >> site
    cdn >> Edge(label="POST signed with OAC SigV4;\nresponse streamed back (spike M1-07)", forward=True, reverse=True) >> api
    api >> Edge(style="dashed", label="fallback: start job, poll status") >> jobs
