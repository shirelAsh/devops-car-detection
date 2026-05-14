# AWS CDK (Python) — S3 for car-detector

Use this to create the **S3 bucket** with encryption, block public access, and TLS-only (`enforce_ssl=True`). Good for interviews: shows **IaC**, **least exposure**, and **repeatable** environments.

## Prerequisites

- **Node.js** (LTS) — CDK CLI uses `npx`
- **Python 3.11+**
- **AWS CLI** configured (`aws sts get-caller-identity` works)
- **CDK CLI**: `npm install -g aws-cdk` (or use `npx aws-cdk@2 ...` below)

## One-time: CDK bootstrap (per account + region)

```powershell
cd c:\Users\david\MyProject\devops-car-detection\infra\cdk
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Set region you use for the assignment (must match docker-compose / app)
$env:CDK_DEFAULT_REGION = "eu-west-1"
$env:CDK_DEFAULT_ACCOUNT = (aws sts get-caller-identity --query Account --output text)

cdk bootstrap "aws://$($env:CDK_DEFAULT_ACCOUNT)/$($env:CDK_DEFAULT_REGION)"
```

## Deploy bucket

**Option A — CDK generates a unique bucket name** (simplest):

```powershell
cdk deploy
```

**Option B — stable name** (must be **globally** unique across all AWS):

```powershell
cdk deploy -c bucketName=david-car-detector-data-2026-euwest1
```

Copy the **output** `BucketName` from CloudFormation; use it as `S3_BUCKET` in Docker / Jenkins / Helm.

## Destroy (removes bucket and objects because of `auto_delete_objects`)

```powershell
cdk destroy
```

For a **submission** bucket you want to keep, change `removal_policy` and `auto_delete_objects` in `car_detector_stack.py` before deploying.

## Interview talking points

- **IaC**: same bucket in dev/stage/prod via parameters or separate stacks.
- **Security**: no public access, SSE-S3, HTTPS-only to the bucket API.
- **Next step**: attach **IAM policies** (user or IRSA role) with `s3:GetObject` / `s3:PutObject` scoped to `arn:aws:s3:::bucket-name/*` — often a second stack or a separate “runtime roles” construct.
