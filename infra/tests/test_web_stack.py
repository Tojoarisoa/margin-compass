"""M1-07 web stack: one CloudFront distribution for site, snapshots, and the agent API (synth only)."""

from __future__ import annotations

import json

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Annotations, Match, Template

from margin_compass_infra.data_stack import DataStack
from margin_compass_infra.guardrails import ForbiddenResourceGuard
from margin_compass_infra.state_stack import StateStack
from margin_compass_infra.tagging import REQUIRED_TAG_KEYS, apply_tags
from margin_compass_infra.web_stack import API_RESERVED_CONCURRENCY, WebStack

ACCOUNT = "123456789012"


@pytest.fixture(scope="module")
def synth():
    app = cdk.App()
    env = cdk.Environment(account=ACCOUNT, region="us-east-1")
    state = StateStack(app, "State", env_name="dev", env=env)
    data = DataStack(app, "Data", env_name="dev", core_table=state.core, env=env)
    web = WebStack(app, "Web", env_name="dev", lake_bucket_name=data.lake.bucket_name, core_table=state.core, env=env)
    for s in (state, data, web):
        apply_tags(s, project="margin-compass", env="dev", stage="web", owner="acme", cost_center="margin-compass")
    cdk.Aspects.of(app).add(ForbiddenResourceGuard())
    return web, Template.from_stack(web), Template.from_stack(data)


def _statements(t):
    return [s for p in t.find_resources("AWS::IAM::Policy").values() for s in p["Properties"]["PolicyDocument"]["Statement"]]


def _actions(s):
    return s["Action"] if isinstance(s["Action"], list) else [s["Action"]]


def test_three_behaviors_on_one_distribution(synth):
    _, t, _ = synth
    dist = next(iter(t.find_resources("AWS::CloudFront::Distribution").values()))["Properties"]["DistributionConfig"]
    assert {b["PathPattern"] for b in dist["CacheBehaviors"]} == {"/publish/*", "/api/*"}
    assert dist["DefaultCacheBehavior"]["ViewerProtocolPolicy"] == "redirect-to-https"
    assert dist["DefaultRootObject"] == "index.html" and dist["PriceClass"] == "PriceClass_100"
    api = next(b for b in dist["CacheBehaviors"] if b["PathPattern"] == "/api/*")
    assert api["ViewerProtocolPolicy"] == "https-only" and "POST" in api["AllowedMethods"]
    site = next(o for o in dist["Origins"] if o.get("OriginPath") == "/site")
    assert "OriginAccessControlId" in site


def test_api_is_only_reachable_through_cloudfront(synth):
    _, t, _ = synth
    t.has_resource_properties("AWS::Lambda::Url", {"AuthType": "AWS_IAM"})
    perms = [p["Properties"] for p in t.find_resources("AWS::Lambda::Permission").values()]
    assert {p["Action"] for p in perms} == {"lambda:InvokeFunctionUrl", "lambda:InvokeFunction"}
    assert all(p["Principal"] == "cloudfront.amazonaws.com" and "distribution/" in json.dumps(p["SourceArn"]) for p in perms)


def test_api_request_policy_never_forwards_host_or_cookies(synth):
    _, t, _ = synth
    cfg = next(iter(t.find_resources("AWS::CloudFront::OriginRequestPolicy").values()))["Properties"]["OriginRequestPolicyConfig"]
    headers = {h.lower() for h in cfg["HeadersConfig"]["Headers"]}
    assert "host" not in headers and "cloudfront-viewer-address" in headers  # x-amz-content-sha256 is rejected by CloudFront here
    assert "authorization" not in headers and "x-mc-owner-token" in headers  # Authorization carries the OAC signature
    assert cfg["CookiesConfig"]["CookieBehavior"] == "none"


def test_api_lambda_is_bounded_and_never_retries_async_jobs(synth):
    _, t, _ = synth
    t.has_resource_properties("AWS::Lambda::Function", {"FunctionName": "mc-dev-web-api", "PackageType": "Image",
                                                        "ReservedConcurrentExecutions": API_RESERVED_CONCURRENCY, "Timeout": 60})
    t.has_resource_properties("AWS::Lambda::EventInvokeConfig", {"MaximumRetryAttempts": 0, "MaximumEventAgeInSeconds": 300})


def test_api_worker_enables_prompt_caching(synth):
    _, t, _ = synth
    fn = next(f for f in t.find_resources("AWS::Lambda::Function").values()
              if f["Properties"].get("FunctionName") == "mc-dev-web-api")
    assert fn["Properties"]["Environment"]["Variables"]["MC_CACHE_PROMPT"] == "1"


def test_api_role_least_privilege(synth):
    web, t, _ = synth
    role_id = web.get_logical_id(web.api.role.node.default_child)
    policies = t.find_resources("AWS::IAM::Policy", {"Properties": {"Roles": [{"Ref": role_id}]}})
    stmts = [s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]]
    actions = {a for s in stmts for a in _actions(s)}
    assert actions == {"s3:GetObject", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "bedrock:InvokeModel",
                       "lambda:InvokeFunction", "logs:CreateLogStream", "logs:PutLogEvents"}
    bedrock = next(s for s in stmts if "bedrock:InvokeModel" in _actions(s))
    blob = json.dumps(bedrock["Resource"])
    assert "claude-haiku-4-5" in blob and "*" not in blob.replace("\"*\"", "")
    s3 = next(s for s in stmts if "s3:GetObject" in _actions(s))
    assert "gold/*.parquet" in json.dumps(s3["Resource"])


def test_security_headers(synth):
    _, t, _ = synth
    cfg = next(iter(t.find_resources("AWS::CloudFront::ResponseHeadersPolicy").values()))["Properties"]["ResponseHeadersPolicyConfig"]
    csp = cfg["SecurityHeadersConfig"]["ContentSecurityPolicy"]["ContentSecurityPolicy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-eval" not in csp
    connect = next(d for d in csp.split(";") if d.strip().startswith("connect-src")).split()[1:]
    assert connect == ["'self'", "https://cognito-idp.us-east-1.amazonaws.com"]  # owner sign-in only, no wildcard
    assert cfg["SecurityHeadersConfig"]["FrameOptions"]["FrameOption"] == "DENY"


def test_lake_lets_cloudfront_read_only_site_and_publish(synth):
    _, _, data = synth
    pol = next(iter(data.find_resources("AWS::S3::BucketPolicy").values()))["Properties"]["PolicyDocument"]["Statement"]
    cf = [s for s in pol if s.get("Principal", {}).get("Service") == "cloudfront.amazonaws.com"]
    assert len(cf) == 1 and cf[0]["Action"] == "s3:GetObject"
    res = json.dumps(cf[0]["Resource"])
    assert "/site/*" in res and "/publish/*" in res and "/gold/" not in res
    assert cf[0]["Condition"]["StringEquals"]["aws:SourceAccount"] == ACCOUNT


def test_tags_and_guardrails(synth):
    web, t, _ = synth
    for resource in t.to_json()["Resources"].values():
        tags = resource.get("Properties", {}).get("Tags")
        if isinstance(tags, list):
            assert set(REQUIRED_TAG_KEYS) <= {tag["Key"] for tag in tags}, resource["Type"]
    Annotations.from_stack(web).has_no_error("*", Match.any_value())


def test_api_role_is_a_kill_switch_target():
    from pathlib import Path

    ctx = json.loads((Path(__file__).resolve().parents[1] / "cdk.json").read_text())["context"]
    assert "mc-dev-web-api" in ctx["mc:killSwitchRoleNames"]


def test_no_bucket_deployment_with_lake_wide_write(synth):
    """The dashboard is uploaded by scripts/deploy-dashboard.sh, not by a Lambda that could write the whole lake."""
    _, t, _ = synth
    t.resource_count_is("Custom::CDKBucketDeployment", 0)
    assert not [s for s in _statements(t) if any(a.startswith(("s3:Put", "s3:Delete", "s3:Abort")) for a in _actions(s))]


# --- dashboard custom domain (medtech.booncore.com) ---------------------------------------------------

def test_custom_domain_adds_a_dns_validated_certificate_and_alias():
    app = cdk.App()
    env = cdk.Environment(account=ACCOUNT, region="us-east-1")
    state = StateStack(app, "S", env_name="dev", env=env)
    data = DataStack(app, "D", env_name="dev", core_table=state.core, env=env)
    web = WebStack(app, "W", env_name="dev", lake_bucket_name=data.lake.bucket_name, core_table=state.core,
                   dashboard_domain="medtech.example.com", env=env)
    t = Template.from_stack(web)
    t.has_resource_properties("AWS::CertificateManager::Certificate",
                              {"DomainName": "medtech.example.com", "ValidationMethod": "DNS"})
    dist = next(iter(t.find_resources("AWS::CloudFront::Distribution").values()))["Properties"]["DistributionConfig"]
    assert dist["Aliases"] == ["medtech.example.com"]
    assert dist["ViewerCertificate"]["SslSupportMethod"] == "sni-only"
    assert dist["ViewerCertificate"]["MinimumProtocolVersion"] == "TLSv1.2_2021"
    t.has_output("DashboardUrl", {"Value": "https://medtech.example.com"})


def test_no_custom_domain_by_default(synth):
    _, t, _ = synth
    t.resource_count_is("AWS::CertificateManager::Certificate", 0)
    assert "Aliases" not in next(iter(t.find_resources("AWS::CloudFront::Distribution").values()))["Properties"]["DistributionConfig"]


def test_cdk_json_sets_the_medtech_dashboard_domain():
    from pathlib import Path

    ctx = json.loads((Path(__file__).resolve().parents[1] / "cdk.json").read_text())["context"]
    assert ctx["mc:dashboardDomain"] == "medtech.booncore.com"


# --- owner sign-in (M5-03 step 5) ------------------------------------------------------------------

def test_owner_pool_is_closed_and_free_tier(synth):
    _, t, _ = synth
    pools = t.find_resources("AWS::Cognito::UserPool")
    assert len(pools) == 1
    pool = next(iter(pools.values()))
    props = pool["Properties"]
    assert props["UserPoolName"] == "mc-dev-web-owners"
    assert props["UserPoolTier"] == "LITE"
    assert props["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True  # no self sign-up
    assert props["Policies"]["PasswordPolicy"]["MinimumLength"] >= 14
    assert props["DeletionProtection"] == "ACTIVE" and pool["DeletionPolicy"] == "Retain"
    t.resource_count_is("AWS::Cognito::UserPoolDomain", 0)  # no hosted UI
    t.has_resource_properties("AWS::Cognito::UserPoolGroup", {"GroupName": "owner"})


def test_no_users_are_created_by_iac(synth):
    _, t, _ = synth
    for typ in ("AWS::Cognito::UserPoolUser", "AWS::Cognito::UserPoolUserToGroupAttachment"):
        t.resource_count_is(typ, 0)


def test_dashboard_client_is_public_srp_only(synth):
    _, t, _ = synth
    client = next(iter(t.find_resources("AWS::Cognito::UserPoolClient").values()))["Properties"]
    assert client.get("GenerateSecret") is False
    assert set(client["ExplicitAuthFlows"]) == {"ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"}
    assert client["PreventUserExistenceErrors"] == "ENABLED" and client["EnableTokenRevocation"] is True
    assert not client.get("AllowedOAuthFlows")
    # Cognito rejects a client that allows OAuth without flows and scopes (deploy of 7a26505 rolled back)
    assert client.get("AllowedOAuthFlowsUserPoolClient") is not True and not client.get("AllowedOAuthScopes")
    assert not client.get("CallbackURLs")


def test_api_knows_the_owner_pool(synth):
    _, t, _ = synth
    fn = next(f for f in t.find_resources("AWS::Lambda::Function").values()
              if f["Properties"].get("FunctionName") == "mc-dev-web-api")
    env = fn["Properties"]["Environment"]["Variables"]
    assert "Ref" in env["OWNER_POOL_ID"] and "Ref" in env["OWNER_CLIENT_ID"]


def test_api_errors_alarm_to_the_alert_topic(synth):
    _, t, _ = synth
    t.resource_count_is("AWS::CloudWatch::Alarm", 1)  # M6-01; §14 allows 10 in the account
    alarm = next(iter(t.find_resources("AWS::CloudWatch::Alarm").values()))["Properties"]
    assert alarm["AlarmName"] == "mc-dev-web-api-errors"
    assert (alarm["MetricName"], alarm["Statistic"], alarm["Period"], alarm["Threshold"]) == ("Errors", "Sum", 3600, 3)
    assert alarm["TreatMissingData"] == "notBreaching" and "mc-shared-foundation-alerts" in json.dumps(alarm["AlarmActions"])
