# tests/test_cloud_providers.py
#
# Unit tests for the multi-cloud provider abstraction.
# Verifies pricing lookup, service resolution, and cost estimation
# for AWS, Azure, and GCP providers. No LLM calls required.

import pytest
from pipeline.cloud_providers import get_provider
from pipeline.cloud_providers.aws   import AWSProvider
from pipeline.cloud_providers.azure import AzureProvider
from pipeline.cloud_providers.gcp   import GCPProvider
from pipeline.cost_calculator import estimate_cost



class TestProviderRegistry:

    def test_get_aws_provider(self):
        p = get_provider("aws")
        assert isinstance(p, AWSProvider)
        assert p.provider_id == "aws"

    def test_get_azure_provider(self):
        p = get_provider("azure")
        assert isinstance(p, AzureProvider)
        assert p.provider_id == "azure"

    def test_get_gcp_provider(self):
        p = get_provider("gcp")
        assert isinstance(p, GCPProvider)
        assert p.provider_id == "gcp"

    def test_agnostic_returns_aws(self):
        p = get_provider("agnostic")
        assert isinstance(p, AWSProvider)

    def test_unknown_returns_aws(self):
        p = get_provider("oracle")
        assert isinstance(p, AWSProvider)

    def test_case_insensitive(self):
        assert get_provider("AWS").provider_id == "aws"
        assert get_provider("Azure").provider_id == "azure"
        assert get_provider("GCP").provider_id == "gcp"



class TestAWSProvider:
    p = AWSProvider()

    def test_ecs_resolves(self):
        assert self.p.resolve_key("Amazon ECS Fargate") is not None

    def test_lambda_resolves(self):
        assert self.p.resolve_key("AWS Lambda") == "lambda"

    def test_dynamodb_resolves(self):
        assert self.p.resolve_key("Amazon DynamoDB") == "dynamodb"

    def test_cloudfront_resolves(self):
        assert self.p.resolve_key("Amazon CloudFront") == "cloudfront"

    def test_unknown_returns_none(self):
        assert self.p.resolve_key("Some Nonexistent Service XYZ") is None

    def test_networking_anchor_is_vpc(self):
        assert self.p.networking_anchor == "VPC"

    def test_data_transfer_in_pricing(self):
        assert "data_transfer" in self.p.pricing

    def test_optimization_tip_nonempty(self):
        assert len(self.p.optimization_tip) > 10



class TestAzureProvider:
    p = AzureProvider()

    def test_azure_functions_resolves(self):
        assert self.p.resolve_key("Azure Functions") == "azure_functions"

    def test_container_apps_resolves(self):
        assert self.p.resolve_key("Azure Container Apps") == "aca"

    def test_cosmos_db_resolves(self):
        assert self.p.resolve_key("Cosmos DB") == "cosmos_db"

    def test_app_gateway_resolves(self):
        assert self.p.resolve_key("Azure Application Gateway") == "app_gateway"

    def test_blob_storage_resolves(self):
        assert self.p.resolve_key("Azure Blob Storage") == "blob_storage"

    def test_key_vault_resolves(self):
        assert self.p.resolve_key("Azure Key Vault") == "key_vault"

    def test_networking_anchor_is_vnet(self):
        assert "virtual network" in self.p.networking_anchor.lower()

    def test_data_transfer_in_pricing(self):
        assert "data_transfer" in self.p.pricing

    def test_aks_resolves(self):
        assert self.p.resolve_key("AKS") == "aks"

    def test_redis_resolves(self):
        assert self.p.resolve_key("Azure Cache for Redis") == "azure_redis"



class TestGCPProvider:
    p = GCPProvider()

    def test_cloud_run_resolves(self):
        assert self.p.resolve_key("Cloud Run") == "cloud_run"

    def test_cloud_functions_resolves(self):
        assert self.p.resolve_key("Cloud Functions") == "cloud_functions"

    def test_bigquery_resolves(self):
        assert self.p.resolve_key("BigQuery") == "bigquery"

    def test_cloud_spanner_resolves(self):
        assert self.p.resolve_key("Cloud Spanner") == "cloud_spanner"

    def test_pub_sub_resolves(self):
        key = self.p.resolve_key("Cloud Pub/Sub")
        assert key == "cloud_pubsub"

    def test_gke_resolves(self):
        assert self.p.resolve_key("Google Kubernetes Engine") == "gke"

    def test_cloud_armor_resolves(self):
        assert self.p.resolve_key("Cloud Armor") == "cloud_armor"

    def test_memorystore_resolves(self):
        assert self.p.resolve_key("Memorystore for Redis") == "memorystore_redis"

    def test_networking_anchor_is_vpc_network(self):
        assert "vpc" in self.p.networking_anchor.lower()

    def test_vertex_ai_resolves(self):
        assert self.p.resolve_key("Vertex AI") == "vertex_ai"



class TestMultiCloudCostEstimation:

    def _arch(self, *services):
        return {"layers": {"compute": list(services), "database": [], "networking": [],
                           "edge": [], "monitoring": [], "security": []}}

    def test_aws_estimate_returns_provider_id(self):
        result = estimate_cost(self._arch("AWS Lambda"), {"cloud_provider": "aws"})
        assert result.get("cloud_provider") == "aws"

    def test_azure_estimate_returns_provider_id(self):
        result = estimate_cost(
            {"layers": {"compute": ["Azure Functions"], "database": [],
                        "networking": ["Azure Virtual Network"], "edge": [],
                        "monitoring": [], "security": []}},
            {"cloud_provider": "azure"}
        )
        assert result.get("cloud_provider") == "azure"

    def test_gcp_estimate_returns_provider_id(self):
        result = estimate_cost(
            {"layers": {"compute": ["Cloud Run"], "database": [],
                        "networking": ["VPC Network"], "edge": [],
                        "monitoring": [], "security": []}},
            {"cloud_provider": "gcp"}
        )
        assert result.get("cloud_provider") == "gcp"

    def test_azure_functions_is_priced(self):
        result = estimate_cost(
            {"layers": {"compute": ["Azure Functions"], "database": [], "networking": [],
                        "edge": [], "monitoring": [], "security": []}},
            {"cloud_provider": "azure"}
        )
        services = [s["service"].lower() for s in result["monthly_breakdown"]]
        assert any("function" in s for s in services)

    def test_gcp_bigquery_is_priced(self):
        result = estimate_cost(
            {"layers": {"compute": [], "database": ["BigQuery"], "networking": [],
                        "edge": [], "monitoring": [], "security": []}},
            {"cloud_provider": "gcp"}
        )
        services = [s["service"].lower() for s in result["monthly_breakdown"]]
        assert any("bigquery" in s for s in services)

    def test_aws_services_not_priced_under_azure(self):
        # "AWS Lambda" should not resolve in the Azure pricing table
        result = estimate_cost(
            {"layers": {"compute": ["AWS Lambda"], "database": [], "networking": [],
                        "edge": [], "monitoring": [], "security": []}},
            {"cloud_provider": "azure"}
        )
        # Only data transfer baseline should be priced
        priced = [s for s in result["monthly_breakdown"] if "transfer" not in s["service"].lower()]
        assert priced == []

    def test_all_providers_have_data_transfer_baseline(self):
        arch = {"layers": {}}
        for cloud in ("aws", "azure", "gcp"):
            result = estimate_cost(arch, {"cloud_provider": cloud})
            assert result["total_monthly_usd"] > 0, f"{cloud} should have a data-transfer baseline"

    def test_optimization_tip_differs_by_provider(self):
        aws_tip   = estimate_cost({"layers": {}}, {"cloud_provider": "aws"})["optimization"]
        azure_tip = estimate_cost({"layers": {}}, {"cloud_provider": "azure"})["optimization"]
        gcp_tip   = estimate_cost({"layers": {}}, {"cloud_provider": "gcp"})["optimization"]
        assert aws_tip != azure_tip
        assert aws_tip != gcp_tip

    def test_provider_kwarg_overrides_requirements(self):
        # Passing an explicit provider object overrides cloud_provider in requirements
        gcp = get_provider("gcp")
        result = estimate_cost({"layers": {}}, {"cloud_provider": "aws"}, provider=gcp)
        assert result["cloud_provider"] == "gcp"
