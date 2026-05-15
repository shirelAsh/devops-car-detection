# Submission screenshots

Evidence for the DevOps practical test (Jenkins, ECR, EKS, S3 metrics).

**Populate images:** run `.\screenshots\copy-from-cursor-assets.ps1` from the repo root, or copy your PNGs here using the filenames below.

## Jenkins

### Metrics and SUCCESS

![Jenkins console: confusion matrix, precision/recall/accuracy, Metrics written to S3](jenkins-metrics-success.png)

![Jenkins pipeline finished SUCCESS](jenkins-finished-success.png)

### ECR push

![Jenkins log: car-detector image pushed to ECR](jenkins-ecr-push.png)

## Amazon ECR

![ECR repository car-detector with image tags v1 and 15](ecr-car-detector-tags.png)

## Amazon EKS

![EKS cluster car-detector-eks Active](eks-cluster-active.png)

![kubectl get jobs - Complete 1/1](kubectl-get-jobs.png)

![EKS pod logs: confusion matrix and metrics written to S3](eks-pod-logs-metrics.png)

![kubectl describe pod: Succeeded, exit code 0, ECR image car-detector:15](eks-describe-pod-success.png)

![Pod environment: IRSA AWS_ROLE_ARN and successful image pull](eks-describe-pod-irsa.png)
