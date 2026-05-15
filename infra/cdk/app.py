#!/usr/bin/env python3
import os

import aws_cdk as cdk

from car_detector_stack import CarDetectorStack
from ecr_stack import CarDetectorEcrStack

app = cdk.App()

# Optional: pass bucket name so it is stable (must be globally unique for S3)
bucket_name = app.node.try_get_context("bucketName")
# Optional: stable ECR repo name (must not already exist in account/region)
ecr_repository_name = app.node.try_get_context("ecrRepositoryName")

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "eu-west-1"),
)

CarDetectorStack(
    app,
    "CarDetectorDataStack",
    bucket_name=bucket_name,
    env=env,
    description="S3 bucket for car-detector video, labels, and metrics output",
)

CarDetectorEcrStack(
    app,
    "CarDetectorEcrStack",
    repository_name=ecr_repository_name,
    env=env,
    description="ECR repository for car-detector container image",
)

# EKS: opt-in — adds a VPC lookup at synth time and deploys a billable control plane + nodes.
#   cdk synth -c enableEks=true
#   cdk deploy CarDetectorEksStack -c enableEks=true
if str(app.node.try_get_context("enableEks") or "").lower() in ("1", "true", "yes"):
    from eks_stack import CarDetectorEksStack

    CarDetectorEksStack(
        app,
        "CarDetectorEksStack",
        env=env,
        description="Minimal EKS cluster (default VPC) for Helm / IRSA lab work",
    )

app.synth()
