# Deploying the site

`web/` is published at <https://clock.cartercole.net/> from a private S3 bucket behind a
CloudFront distribution. The bucket is readable only by the distribution, so the files are
never reachable over an S3 URL; HTTPS and the cache headers cannot be bypassed.

| | |
|---|---|
| bucket | `s3://clock.cartercole.net` (us-east-1, private, SSE-AES256) |
| distribution | `EM145PSSAP954` → `d3j3f8tnktqc41.cloudfront.net` |
| DNS | `clock.cartercole.net` A + AAAA alias, zone `Z0427813IYIATECN8E9D` |
| certificate | ACM in us-east-1, DNS-validated |

`scripts/deploy.sh` uploads the site and invalidates the CDN. It is idempotent — running it
twice changes nothing the second time. GitHub Actions runs it on every push to `main` that
passes the tests; to publish by hand with AWS credentials in the environment:

```sh
scripts/deploy.sh
```

It ships `web/` minus the tooling that lives there (`test/`, `build_docs.py`,
`package.json`). `Content-Type` and `Cache-Control` are set per file at upload time, because
the distribution's managed `CachingOptimized` policy obeys whatever the origin sends: HTML
revalidates on every request, everything else is cached for a day and covered by the
per-deploy invalidation.

`docs.html` is generated — run `python3 web/build_docs.py` after editing
`protocol/PROTOCOL.md` and commit the result, or the published protocol page will lag the
source.

## How CI gets into AWS

The deploy job assumes an IAM role through GitHub's OIDC provider, so there are no AWS keys
stored in the repository. Two things have to exist in account `352441492542`, both created
once by hand:

**1. The OIDC provider**, if the account does not already have one — IAM → Identity providers
→ Add provider → OpenID Connect, with provider URL `https://token.actions.githubusercontent.com`
and audience `sts.amazonaws.com`.

**2. A role** — call it `intervalclock-deploy` — with this trust policy. The `sub` condition
is what keeps the role pinned to this repository's `main` branch; without it any workflow on
GitHub could assume it.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::352441492542:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:CarterCole/intervalclock:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

and this permission policy, which reaches exactly one bucket and one distribution:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::clock.cartercole.net"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::clock.cartercole.net/*"
    },
    {
      "Effect": "Allow",
      "Action": "cloudfront:CreateInvalidation",
      "Resource": "arn:aws:cloudfront::352441492542:distribution/EM145PSSAP954"
    }
  ]
}
```

Then point the workflow at it:

```sh
gh variable set AWS_DEPLOY_ROLE_ARN \
  --repo CarterCole/intervalclock \
  --body arn:aws:iam::352441492542:role/intervalclock-deploy
```

Until that variable is set the `deploy` job fails at the credentials step; the `test` job is
unaffected.
