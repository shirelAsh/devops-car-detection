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

Deploy **only** the data stack (recommended if you already manage ECR elsewhere):

```powershell
cdk deploy CarDetectorDataStack
```

Or deploy **everything** defined in `app.py` (S3 + ECR):

```powershell
cdk deploy --all
```

**Stable bucket name** (must be **globally** unique across all AWS):

```powershell
cdk deploy CarDetectorDataStack -c bucketName=david-car-detector-data-2026-euwest1
```

Copy the **output** `BucketName` from CloudFormation; use it as `S3_BUCKET` in Docker / Jenkins / Helm.

## Deploy ECR repository (optional second stack)

Creates a private **ECR** repo for the detector image (scan on push). See also [`docs/ECR_AND_IRSA.md`](../../docs/ECR_AND_IRSA.md).

```powershell
# Same venv / CDK_DEFAULT_* as above. Optional stable name:
cdk deploy CarDetectorEcrStack -c ecrRepositoryName=car-detector
```

Outputs: **RepositoryUri**, **RepositoryName**. For Jenkins `ECR_REGISTRY` / `ECR_REPOSITORY`, split the URI (host vs path — see the doc).

## Destroy (removes bucket and objects because of `auto_delete_objects`)

```powershell
cdk destroy CarDetectorDataStack
cdk destroy CarDetectorEcrStack
```

For a **submission** bucket you want to keep, change `removal_policy` and `auto_delete_objects` in `car_detector_stack.py` before deploying.

## Interview talking points

- **IaC**: same bucket in dev/stage/prod via parameters or separate stacks.
- **Security**: no public access, SSE-S3, HTTPS-only to the bucket API.
- **Next step**: attach **IAM policies** (user or IRSA role) with `s3:GetObject` / `s3:PutObject` scoped to `arn:aws:s3:::bucket-name/*` — often a second stack or a separate “runtime roles” construct.
