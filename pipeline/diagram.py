# pipeline/diagram.py
#
# Converts architecture layers into a Mermaid flowchart diagram.
# No LLM needed — generates the diagram programmatically from the service list.
#
# Output is a Mermaid string that the frontend renders as an SVG diagram.

def generate_mermaid(architecture: dict) -> str:
    """Generate a Mermaid flowchart from an architecture layers dict.

    Args:
        architecture: dict with "layers" key containing service lists

    Returns Mermaid diagram string starting with "graph TD"
    """

    layers = architecture.get("layers", {})

    # Collect services per layer (skip empty layers)
    edge       = layers.get("edge", [])
    networking = layers.get("networking", [])
    compute    = layers.get("compute", [])
    database   = layers.get("database", [])
    messaging  = layers.get("messaging", [])
    monitoring = layers.get("monitoring", [])

    lines = ["graph TD"]
    lines.append("    User([User / Client])")

    import re

    # Helper: make a safe Mermaid node ID.
    # Mermaid node IDs must be alphanumeric + underscores only.
    # The LLM sometimes returns names like:
    #   "Amazon CloudWatch, AWS X-Ray"  → take first token before comma
    #   "Amazon SQS (for async)"        → strip parenthetical
    def node_id(name):
        s = name.split(",")[0].strip()              # first comma-separated token
        s = re.sub(r"\s*\(.*?\)", "", s).strip()   # remove "(qualifier)"
        return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")

    # Helper: short display label (strip "Amazon " / "AWS " for cleaner nodes)
    def display_label(name):
        s = name.split(",")[0].strip()
        s = re.sub(r"\s*\(.*?\)", "", s).strip()
        for prefix in ("Amazon ", "AWS ", "Azure ", "Google ", "GCP "):
            if s.startswith(prefix):
                return s[len(prefix):]
        return s

    # Helper: add a layer of services to the diagram
    def add_layer(services, shape_open="[", shape_close="]"):
        for svc in services:
            nid   = node_id(svc)
            label = display_label(svc)
            lines.append(f"    {nid}{shape_open}{label}{shape_close}")

    # Build nodes by layer
    if edge:
        add_layer(edge)
    if networking:
        add_layer(networking)
    if compute:
        add_layer(compute)
    if database:
        add_layer(database, "[(", ")]")  # cylinder shape for databases
    if messaging:
        add_layer(messaging)
    if monitoring:
        add_layer(monitoring)

    # Build edges — flow: User → edge → networking → compute → database/messaging
    def connect(from_services, to_services, label=""):
        arrow = f"-->|{label}|" if label else "-->"
        for src in from_services:
            for dst in to_services:
                lines.append(f"    {node_id(src)} {arrow} {node_id(dst)}")

    # User connects to the first available layer
    first_layer = edge or networking or compute
    for svc in first_layer:
        lines.append(f"    User --> {node_id(svc)}")

    if edge and networking:
        connect(edge, networking)
    if networking and compute:
        connect(networking, compute)
    if compute and database:
        connect(compute, database)
    if compute and messaging:
        connect(compute, messaging)
    if compute and monitoring:
        connect(compute, monitoring, label="metrics")

    return "\n".join(lines)


if __name__ == "__main__":
    # Quick test
    test_arch = {
        "layers": {
            "edge":       ["CloudFront"],
            "networking": ["ALB"],
            "compute":    ["ECS Fargate"],
            "database":   ["Aurora PostgreSQL", "ElastiCache"],
            "messaging":  ["SQS"],
            "monitoring": ["CloudWatch"],
        }
    }

    diagram = generate_mermaid(test_arch)
    print(diagram)
