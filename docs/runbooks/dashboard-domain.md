# Dashboard custom domain

The dashboard is served at **https://medtech.booncore.com** (medical-device and imaging segment). The
`booncore.com` zone is in **Cloudflare**, not Route 53, so DNS records are added there with the `cf` CLI.
A later segment (for example `telecom.booncore.com`) follows the same steps with its own certificate.

| Piece | Where | Set by |
| --- | --- | --- |
| ACM certificate for the subdomain (us-east-1, DNS validation) | `mc-dev-web` | CDK, context `mc:dashboardDomain` in `infra/cdk.json` |
| CloudFront alternate domain name (alias) | `mc-dev-web` distribution | CDK, same context |
| ACM validation CNAME (`_<token>.medtech` → `_<token>.acm-validations.aws`) | Cloudflare, DNS only | once, by hand with `cf` |
| `medtech` CNAME → the distribution's `*.cloudfront.net` name | Cloudflare, **DNS only** (grey cloud) | once, by hand with `cf` |

Cost: $0 (public ACM certificates are free; CloudFront aliases are free).

## First deploy

1. Merge the change; `deploy to dev` starts and `mc-dev-web` waits until the certificate is validated.
2. While it waits, read the validation record and add it to Cloudflare:

   ```bash
   arn=$(aws acm list-certificates --region us-east-1 --query "CertificateSummaryList[?DomainName=='medtech.booncore.com'].CertificateArn" --output text)
   aws acm describe-certificate --region us-east-1 --certificate-arn "$arn" --query 'Certificate.DomainValidationOptions[0].ResourceRecord'
   cf dns records create -z booncore.com --type CNAME --name <Name without the zone> --content <Value> --proxied false
   ```

   ACM issues the certificate within minutes and the deploy continues.
3. Point the subdomain at CloudFront (the `Url` output of `mc-dev-web`, without `https://`):

   ```bash
   cf dns records create -z booncore.com --type CNAME --name medtech --content <dxxxx.cloudfront.net> --proxied false
   ```

Keep both records **DNS only**: proxying through Cloudflare would put a second CDN and TLS hop in front
of CloudFront. Keep the validation CNAME: ACM uses it to renew the certificate automatically.
