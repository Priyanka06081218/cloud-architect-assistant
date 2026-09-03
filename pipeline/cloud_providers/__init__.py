# pipeline/cloud_providers/__init__.py
from pipeline.cloud_providers.aws   import AWSProvider
from pipeline.cloud_providers.azure import AzureProvider
from pipeline.cloud_providers.gcp   import GCPProvider

_REGISTRY = {
    "aws":      AWSProvider(),
    "azure":    AzureProvider(),
    "gcp":      GCPProvider(),
    "agnostic": AWSProvider(),   # default to AWS when cloud is unspecified
}


def get_provider(name: str):
    """Return the CloudProvider for the given name (case-insensitive)."""
    return _REGISTRY.get((name or "aws").lower(), AWSProvider())
