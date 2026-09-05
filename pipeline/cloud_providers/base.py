# pipeline/cloud_providers/base.py
#
# Abstract base class for cloud providers.
# Each provider supplies:
#   pricing, service_name_map, networking_anchor, optimization_tip,
#   terraform_provider, compliance_controls, availability_patterns,
#   latency_patterns, multi_region_patterns, budget_suggestion.


class CloudProvider:
    name:              str = ""
    provider_id:       str = ""
    pricing:           dict = {}
    service_name_map:  dict = {}
    networking_anchor: str = "VPC"
    optimization_tip:  str = ""
    terraform_provider: str = ""

    # Marketing prefixes to strip when resolving service names.
    # e.g. "Amazon ECS" → strip "amazon " → "ecs" → look up in service_name_map.
    alias_prefixes: list = []

    # Compliance: dict[standard → list[{keyword, label, reason}]]
    compliance_controls: dict = {}

    # Availability
    ha_database_keywords: list = []
    ha_compute_keywords:  list = []
    ha_lb_keywords:       list = []
    ha_missing_labels: dict = {}   # {"db": "...", "compute": "...", "lb": "..."}
    ha_suggestion: str = ""

    # Latency
    cache_keywords:   list = []
    cdn_keywords:     list = []
    fast_db_keywords: list = []
    latency_suggestion: str = ""

    # Multi-region
    multi_region_keywords:  list = []
    multi_region_suggestion: str = ""

    # Budget
    budget_suggestion: str = ""

    def resolve_key(self, service_name: str) -> str | None:
        """Map a service name string to a pricing key."""
        import re
        raw = service_name.lower().strip()
        if raw in self.service_name_map:
            return self.service_name_map[raw]
        normalized = re.sub(r"\s*\(.*?\)", "", raw).strip()
        for prefix in self.alias_prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
                break
        return self.service_name_map.get(normalized)
