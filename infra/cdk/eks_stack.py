"""
Minimal EKS cluster (EC2 managed node group) for the assignment: Helm + IRSA.

Cost warning: EKS charges for the control plane (~per hour) plus EC2 for nodes.
Destroy the stack when finished: cdk destroy CarDetectorEksStack
"""

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_eks as eks
from aws_cdk import aws_iam as iam
from aws_cdk.lambda_layer_kubectl_v31 import KubectlV31Layer
from constructs import Construct


class CarDetectorEksStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        kubernetes_version: eks.KubernetesVersion = eks.KubernetesVersion.V1_30,
        node_instance_type: ec2.InstanceType | None = None,
        node_desired_size: int = 1,
        node_min_size: int = 1,
        node_max_size: int = 2,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if node_instance_type is None:
            node_instance_type = ec2.InstanceType.of(
                ec2.InstanceClass.T3, ec2.InstanceSize.SMALL
            )

        # Default VPC keeps this stack small (no NAT gateways). Nodes use public subnets.
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        cluster = eks.Cluster(
            self,
            "CarDetectorCluster",
            version=kubernetes_version,
            vpc=vpc,
            vpc_subnets=[
                ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            ],
            default_capacity=0,
            kubectl_layer=KubectlV31Layer(self, "Kubectl31Layer"),
            # API reachable from your IP for kubectl/Helm; tighten for production.
            endpoint_access=eks.EndpointAccess.PUBLIC_AND_PRIVATE,
        )

        ng = cluster.add_nodegroup_capacity(
            "Workers",
            instance_types=[node_instance_type],
            min_size=node_min_size,
            max_size=node_max_size,
            desired_size=node_desired_size,
            ami_type=eks.NodegroupAmiType.AL2023_X86_64_STANDARD,
            capacity_type=eks.CapacityType.ON_DEMAND,
        )

        # Pull images from ECR in this account/region (Helm will use your pushed tag).
        ng.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonEC2ContainerRegistryReadOnly"
            )
        )

        self.cluster = cluster

        CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        CfnOutput(
            self,
            "KubeConfigHint",
            value=f"aws eks update-kubeconfig --region {self.region} --name {cluster.cluster_name}",
        )
        CfnOutput(self, "OidcIssuerUrl", value=cluster.cluster_open_id_connect_issuer_url)
        CfnOutput(
            self,
            "OidcProviderArn",
            value=cluster.open_id_connect_provider.open_id_connect_provider_arn,
        )
