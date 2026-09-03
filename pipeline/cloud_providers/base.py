# pipeline/cloud_providers/base.py
#
# Abstract base class for cloud providers.
# Each provider supplies:
#   - name:              human-readable cloud name ("AWS", "Azure", "GCP")
#   - provider_id:       short slug ("aws", "azure", "gcp")
#   - pricing:           dict[key → {monthly, unit, scalable, global?}]
#   - service_name_map:  dict[lowercase service name → pricing key]
#   - networking_anchor: the "VPC equivalent" service name for VNet injection
#   - optimization_tip:  cloud-specific cost-saving advice
#   - terraform_provider: Terraform provider block stub


class CloudProvider:
    name:              str = ""
    provider_id:       str = ""
    pricing:           dict = {}
    service_name_map:  dict = {}
    networking_anchor: str = "VPC"
    optimization_tip:  str = ""
    terraform_provider: str = ""

    def resolve_key(self, service_name: str) -> str | None:
        """Map a service name string to a pricing key."""
        import re
        raw = service_name.lower().strip()
        if raw in self.service_name_map:
            return self.service_name_map[raw]
        # Strip provider prefix and parenthetical notes, then retry
        normalized = re.sub(r"\s*\(.*?\)", "", raw).strip()
        for prefix in (self.provider_id + " ", self.name.lower() + " "):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
        return self.service_name_map.get(normalized)
