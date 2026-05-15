# ECR and IRSA (then EKS)

Do **ECR** and **IAM policy** first. **IRSA** needs an EKS cluster that already has an **OIDC provider**—complete the [EKS + Helm](../README.md#helm-on-eks) step after this, or use an existing cluster.

---

## 1. ECR — create repository and push an image

### Option A — AWS CLI (fastest)

```powershell
$REGION = "eu-west-1"   # same as AWS_DEFAULT_REGION / cluster
$ACCOUNT = aws sts get-caller-identity --query Account --output text
$REPO = "car-detector"

aws ecr create-repository --repository-name $REPO --region $REGION 2>$null
aws ecr describe-repositories --repository-names $REPO --region $REGION --query repositories[0].repositoryUri --output text
```

Registry host is:

`$ACCOUNT.dkr.ecr.$REGION.amazonaws.com`

**Login, build, tag, push** (from repo root, Docker running):

```powershell
cd c:\Users\david\MyProject\devops-car-detection
$REGION = "eu-west-1"
$ACCOUNT = aws sts get-caller-identity --query Account --output text
$REGISTRY = "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
$REPO = "car-detector"
$TAG = "v1"   # or git sha / Jenkins BUILD_NUMBER

aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REGISTRY

docker compose build detector
docker tag car-detector:local "${REGISTRY}/${REPO}:${TAG}"
docker push "${REGISTRY}/${REPO}:${TAG}"
```

### Option B — CDK (repeatable)

From `infra/cdk` (venv + `pip install -r requirements.txt` as in [infra/cdk/README.md](../infra/cdk/README.md)):

```powershell
$env:CDK_DEFAULT_REGION = "eu-west-1"
$env:CDK_DEFAULT_ACCOUNT = aws sts get-caller-identity --query Account --output text

# Optional stable repo name (must not already exist in the account/region):
cdk deploy CarDetectorEcrStack -c ecrRepositoryName=car-detector
```

Stack outputs: **RepositoryUri**, **RepositoryName**. Use **RepositoryUri** without tag as `ECR_REGISTRY` is wrong—split:

- **ECR_REGISTRY** = `123456789012.dkr.ecr.eu-west-1.amazonaws.com`
- **ECR_REPOSITORY** = `car-detector`

---

## 2. Jenkins — enable “Push to ECR” stage

Set both variables (non-empty) using either **Build with Parameters** (`ECR_REGISTRY`, `ECR_REPOSITORY` in the `Jenkinsfile`) or Jenkins **global / node** environment properties:

| Variable | Example |
|----------|---------|
| `ECR_REGISTRY` | `123456789012.dkr.ecr.eu-west-1.amazonaws.com` |
| `ECR_REPOSITORY` | `car-detector` |

The pipeline exports `CAR_DETECTOR_IMAGE` as `ECR_REGISTRY/ECR_REPOSITORY:$BUILD_NUMBER` when both are set (otherwise `car-detector:local`). The **Push to ECR** stage logs in with `aws ecr get-login-password`, runs `docker compose build`, then `docker compose push`. **Run detector** uses the same `CAR_DETECTOR_IMAGE` so the S3 job runs the image you just pushed.

---

## 3. IRSA — IAM role for the Kubernetes service account

The pod must call S3 **without** long-lived keys. **IRSA** maps an IAM role to the Helm **ServiceAccount** via annotation `eks.amazonaws.com/role-arn`.

### 3a. Prerequisite: OIDC on the cluster

If not already associated:

```bash
eksctl utils associate-iam-oidc-provider --cluster YOUR_CLUSTER_NAME --region YOUR_REGION --approve
```

Get the **OIDC issuer URL** (no `https://` in the ARN you will build—AWS docs show both forms):

```bash
aws eks describe-cluster --name YOUR_CLUSTER_NAME --region YOUR_REGION --query "cluster.identity.oidc.issuer" --output text
```

Example issuer: `https://oidc.eks.eu-west-1.amazonaws.com/id/A1B2C3D4E5F6G7H8I9J0`

**OIDC provider ARN** (console → IAM → Identity providers):

`arn:aws:iam::ACCOUNT_ID:oidc-provider/oidc.eks.REGION.amazonaws.com/id/A1B2C3D4E5F6G7H8I9J0`

### 3b. S3 policy (least privilege)

1. Copy [`infra/iam/s3-detector-policy.json`](../infra/iam/s3-detector-policy.json).
2. Replace `REPLACE_WITH_BUCKET_NAME` with your bucket name (same as `S3_BUCKET`).
3. In IAM → **Create policy** → JSON → paste → name e.g. `CarDetectorS3Runtime`.

### 3c. Trust policy (web identity)

Create an IAM **role** (e.g. `CarDetectorEksS3Role`). Trust entity: **Web identity**.

- **Identity provider**: your EKS OIDC provider (from 3a).
- **Audience**: `sts.amazonaws.com`.
- **Subject** (condition): must match the Kubernetes service account the Job uses.

For default Helm install **release name** `car-detector`, chart `car-detector`, the ServiceAccount name is:

`system:serviceaccount:car-detector:car-detector-car-detector`

(namespace `car-detector`, SA name pattern `RELEASE-CHARTNAME`).

In **JSON trust policy**, use `StringEquals` on:

`oidc.eks.REGION.amazonaws.com/id/OIDC_ID:sub` = `system:serviceaccount:car-detector:car-detector-car-detector`

`oidc.eks.REGION.amazonaws.com/id/OIDC_ID:aud` = `sts.amazonaws.com`

(Replace `REGION`, `OIDC_ID`, and namespace/SA if you change Helm values.)

Attach the **S3 policy** from 3b to this role.

### 3d. One-command alternative (`eksctl`)

If you use **eksctl**, you can create the SA + role + policy attachment in one go (adjust cluster, namespace, policy ARN):

```bash
eksctl create iamserviceaccount \
  --cluster=YOUR_CLUSTER_NAME \
  --region=YOUR_REGION \
  --namespace=car-detector \
  --name=car-detector-car-detector \
  --role-name=CarDetectorEksS3Role \
  --attach-policy-arn=arn:aws:iam::ACCOUNT_ID:policy/CarDetectorS3Runtime \
  --approve \
  --override-existing-serviceaccounts
```

(`--name` must match the Helm ServiceAccount; create namespace first or add `--namespace` after `kubectl create ns`.)

### 3e. Helm — set IRSA annotation

After the role exists:

```bash
helm upgrade --install car-detector ./helm/car-detector -n car-detector --create-namespace \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=arn:aws:iam::ACCOUNT_ID:role/CarDetectorEksS3Role \
  --set image.repository=ACCOUNT.dkr.ecr.REGION.amazonaws.com/car-detector \
  --set image.tag=v1 \
  --set env.S3_BUCKET=your-bucket \
  --set env.S3_VIDEO_KEY=video.mp4 \
  --set env.S3_LABELS_KEY=labels.json \
  --set env.AWS_DEFAULT_REGION=eu-west-1
```

Pods then receive **temporary AWS credentials** via the projected token; the app uses the default credential chain (no `AWS_PROFILE` needed in the pod).

---

## 4. Order checklist

1. **ECR** repo + **push** image tag you will use in Helm.  
2. **S3 policy** JSON → IAM policy.  
3. **EKS cluster** + OIDC associated.  
4. **IRSA role** (trust + policy) or `eksctl create iamserviceaccount`.  
5. **Helm install** with `serviceAccount.annotations` + ECR `image.repository` / `image.tag`.  
6. **Verify** `kubectl get pods -n car-detector` and `kubectl logs`.

---

## 5. EKS node permissions (ECR pull)

Managed node groups usually include **AmazonEC2ContainerRegistryReadOnly** on the node role so kubelet can pull from ECR. If pulls fail with 403, attach that policy to the **node** instance role (not the IRSA role).
