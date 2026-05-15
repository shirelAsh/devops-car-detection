# AWS CDK (Python) — S3 for car-detector

Use this to create the **S3 bucket** with encryption, block public access, and TLS-only (`enforce_ssl=True`). Provides **IaC**, **least exposure**, and **repeatable** environments.

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

## Deploy EKS cluster (optional third stack — **costs money**)

This repo can create a **small EKS cluster** in the **default VPC** (one `t3.small` node by default) so you can run **Helm** + **IRSA** for the assignment. The control plane and EC2 nodes are billed while they exist — **`cdk destroy CarDetectorEksStack -c enableEks=true`** when you are done.

**Prerequisites:** same as above, plus `pip install -r requirements.txt` (adds `aws-cdk-lambda-layer-kubectl-v31`). IAM user/role needs `eks:*` (broadly: use an admin or `AdministratorAccess` for the lab; tighten for production).

**Synth / deploy** (must pass `-c enableEks=true` or the stack is not in the app):

```powershell
$env:CDK_DEFAULT_REGION = "eu-west-1"
$env:CDK_DEFAULT_ACCOUNT = (aws sts get-caller-identity --query Account --output text)

cdk synth -c enableEks=true
cdk deploy CarDetectorEksStack -c enableEks=true
```

After deploy, use the **CloudFormation output** `KubeConfigHint`:

```powershell
aws eks update-kubeconfig --region eu-west-1 --name <ClusterName-from-output>
kubectl get nodes
```

**Destroy** (stops most charges; clean up ENIs if the stack delete stalls):

```powershell
cdk destroy CarDetectorEksStack -c enableEks=true
```
