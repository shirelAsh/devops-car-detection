from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_ecr as ecr
from constructs import Construct


class CarDetectorEcrStack(Stack):
    """Private ECR repository for the detector image (Jenkins / local push)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        repository_name: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.repository = ecr.Repository(
            self,
            "CarDetectorRepository",
            repository_name=repository_name,
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.DESTROY,
        )

        CfnOutput(self, "RepositoryUri", value=self.repository.repository_uri)
        CfnOutput(self, "RepositoryName", value=self.repository.repository_name)
