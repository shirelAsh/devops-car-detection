#!/usr/bin/env python3
import os

import aws_cdk as cdk

from car_detector_stack import CarDetectorStack

app = cdk.App()

# Optional: pass bucket name so it is stable (must be globally unique for S3)
bucket_name = app.node.try_get_context("bucketName")

CarDetectorStack(
    app,
    "CarDetectorDataStack",
    bucket_name=bucket_name,
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "eu-west-1"),
    ),
    description="S3 bucket for car-detector video, labels, and metrics output",
)

app.synth()
