# pipeline/drift_detector.py
#
# Architecture Drift Detector
#
# Scans a real cloud account (AWS, Azure, or GCP) and compares what's deployed
# against what the pipeline recommended. Produces a drift report with
# severity-scored gaps and fix suggestions.

import json
import logging
import time
import base64
from typing import Optional

import requests as _requests

log = logging.getLogger(__name__)

#  Severity levels

CRITICAL = "critical"   # security gap — fix immediately
HIGH     = "high"       # reliability gap — fix before production
MEDIUM   = "medium"     # optimization gap — fix when possible
LOW      = "low"        # nice-to-have improvement

#  AWS Scanner 

def _make_session(aws_access_key_id: str, aws_secret_access_key: str, region: str):
    import boto3
    return boto3.Session(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region,
    )


def _client(session, service: str):
    """Create a boto3 client with explicit SigV4 signing (required by some services)."""
    from botocore.config import Config
    return session.client(service, config=Config(signature_version="v4"))


def scan_aws_account(aws_access_key_id: str, aws_secret_access_key: str, region: str) -> dict:
    """Scan an AWS account and return a snapshot of deployed services.

    Reads: EC2, RDS, ECS, Lambda, CloudFront, ALB/ELB, DynamoDB,
           ElastiCache, SQS, CloudWatch alarms, CloudTrail, GuardDuty.

    Returns a dict with boolean/count fields for each service category.
    """
    session = _make_session(aws_access_key_id, aws_secret_access_key, region)
    snapshot = {}

    #  Compute 
    try:
        ec2 = _client(session,"ec2")
        reservations = ec2.describe_instances(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        )["Reservations"]
        snapshot["ec2_count"] = sum(len(r["Instances"]) for r in reservations)

        # Check for multi-AZ spread
        azs = set()
        for r in reservations:
            for i in r["Instances"]:
                azs.add(i.get("Placement", {}).get("AvailabilityZone", ""))
        snapshot["ec2_multi_az"] = len(azs) > 1
    except Exception as e:
        log.warning(f"EC2 scan failed: {e}")
        snapshot["ec2_count"] = 0
        snapshot["ec2_multi_az"] = False

    #  ECS 
    try:
        ecs = _client(session,"ecs")
        clusters = ecs.list_clusters()["clusterArns"]
        snapshot["ecs_clusters"] = len(clusters)
        snapshot["has_ecs"] = len(clusters) > 0
    except Exception as e:
        log.warning(f"ECS scan failed: {e}")
        snapshot["ecs_clusters"] = 0
        snapshot["has_ecs"] = False

    #  Lambda 
    try:
        lam = _client(session,"lambda")
        functions = lam.list_functions()["Functions"]
        snapshot["lambda_count"] = len(functions)
        snapshot["has_lambda"] = len(functions) > 0
    except Exception as e:
        log.warning(f"Lambda scan failed: {e}")
        snapshot["lambda_count"] = 0
        snapshot["has_lambda"] = False

    #  RDS 
    try:
        rds = _client(session,"rds")
        instances = rds.describe_db_instances()["DBInstances"]
        snapshot["rds_count"] = len(instances)
        snapshot["has_rds"] = len(instances) > 0
        snapshot["rds_multi_az"] = any(i.get("MultiAZ", False) for i in instances)
        snapshot["rds_encrypted"] = all(i.get("StorageEncrypted", False) for i in instances) if instances else False
        snapshot["rds_engines"] = list({i["Engine"] for i in instances})
    except Exception as e:
        log.warning(f"RDS scan failed: {e}")
        snapshot["rds_count"] = 0
        snapshot["has_rds"] = False
        snapshot["rds_multi_az"] = False
        snapshot["rds_encrypted"] = False
        snapshot["rds_engines"] = []

    #  DynamoDB 
    try:
        ddb = _client(session,"dynamodb")
        tables = ddb.list_tables()["TableNames"]
        snapshot["dynamodb_tables"] = len(tables)
        snapshot["has_dynamodb"] = len(tables) > 0
    except Exception as e:
        log.warning(f"DynamoDB scan failed: {e}")
        snapshot["dynamodb_tables"] = 0
        snapshot["has_dynamodb"] = False

    #  ElastiCache 
    try:
        ec = _client(session,"elasticache")
        clusters = ec.describe_cache_clusters()["CacheClusters"]
        snapshot["elasticache_clusters"] = len(clusters)
        snapshot["has_elasticache"] = len(clusters) > 0
    except Exception as e:
        log.warning(f"ElastiCache scan failed: {e}")
        snapshot["elasticache_clusters"] = 0
        snapshot["has_elasticache"] = False

    #  Load Balancers 
    try:
        elb = _client(session,"elbv2")
        lbs = elb.describe_load_balancers()["LoadBalancers"]
        snapshot["alb_count"] = len([lb for lb in lbs if lb["Type"] == "application"])
        snapshot["nlb_count"] = len([lb for lb in lbs if lb["Type"] == "network"])
        snapshot["has_alb"] = snapshot["alb_count"] > 0
    except Exception as e:
        log.warning(f"ALB scan failed: {e}")
        snapshot["alb_count"] = 0
        snapshot["nlb_count"] = 0
        snapshot["has_alb"] = False

    #  CloudFront 
    try:
        cf = _client(session,"cloudfront")
        dists = cf.list_distributions().get("DistributionList", {}).get("Items", [])
        snapshot["cloudfront_distributions"] = len(dists)
        snapshot["has_cloudfront"] = len(dists) > 0
    except Exception as e:
        log.warning(f"CloudFront scan failed: {e}")
        snapshot["cloudfront_distributions"] = 0
        snapshot["has_cloudfront"] = False

    #  SQS 
    try:
        sqs = _client(session,"sqs")
        queues = sqs.list_queues().get("QueueUrls", [])
        snapshot["sqs_queues"] = len(queues)
        snapshot["has_sqs"] = len(queues) > 0
    except Exception as e:
        log.warning(f"SQS scan failed: {e}")
        snapshot["sqs_queues"] = 0
        snapshot["has_sqs"] = False

    #  API Gateway 
    try:
        apigw = _client(session,"apigateway")
        apis = apigw.get_rest_apis()["items"]
        snapshot["api_gateway_count"] = len(apis)
        snapshot["has_api_gateway"] = len(apis) > 0
    except Exception as e:
        log.warning(f"API Gateway scan failed: {e}")
        snapshot["api_gateway_count"] = 0
        snapshot["has_api_gateway"] = False

    #  CloudWatch Alarms 
    try:
        cw = _client(session,"cloudwatch")
        alarms = cw.describe_alarms()["MetricAlarms"]
        snapshot["cloudwatch_alarms"] = len(alarms)
        snapshot["has_cloudwatch_alarms"] = len(alarms) > 0
    except Exception as e:
        log.warning(f"CloudWatch scan failed: {e}")
        snapshot["cloudwatch_alarms"] = 0
        snapshot["has_cloudwatch_alarms"] = False

    #  CloudTrail 
    try:
        ct = _client(session,"cloudtrail")
        trails = ct.describe_trails()["trailList"]
        snapshot["has_cloudtrail"] = len(trails) > 0
        snapshot["cloudtrail_multi_region"] = any(t.get("IsMultiRegionTrail", False) for t in trails)
    except Exception as e:
        log.warning(f"CloudTrail scan failed: {e}")
        snapshot["has_cloudtrail"] = False
        snapshot["cloudtrail_multi_region"] = False

    #  GuardDuty 
    try:
        gd = _client(session,"guardduty")
        detectors = gd.list_detectors()["DetectorIds"]
        snapshot["has_guardduty"] = len(detectors) > 0
    except Exception as e:
        log.warning(f"GuardDuty scan failed: {e}")
        snapshot["has_guardduty"] = False

    #  WAF 
    try:
        waf = _client(session,"wafv2")
        webs = waf.list_web_acls(Scope="REGIONAL")["WebACLs"]
        snapshot["has_waf"] = len(webs) > 0
    except Exception as e:
        log.warning(f"WAF scan failed: {e}")
        snapshot["has_waf"] = False

    #  S3 
    try:
        s3 = _client(session,"s3")
        buckets = s3.list_buckets()["Buckets"]
        snapshot["s3_buckets"] = len(buckets)
        snapshot["has_s3"] = len(buckets) > 0
    except Exception as e:
        log.warning(f"S3 scan failed: {e}")
        snapshot["s3_buckets"] = 0
        snapshot["has_s3"] = False

    snapshot["region"] = region
    return snapshot


#  Service name normalizer 

_SERVICE_KEYWORDS = {
    "cloudfront":   "has_cloudfront",
    "alb":          "has_alb",
    "load balancer":"has_alb",
    "api gateway":  "has_api_gateway",
    "ecs":          "has_ecs",
    "lambda":       "has_lambda",
    "ec2":          "ec2_count",
    "rds":          "has_rds",
    "aurora":       "has_rds",
    "dynamodb":     "has_dynamodb",
    "elasticache":  "has_elasticache",
    "redis":        "has_elasticache",
    "sqs":          "has_sqs",
    "sns":          None,           # not scanned yet
    "cloudwatch":   "has_cloudwatch_alarms",
    "x-ray":        None,
    "xray":         None,
    "waf":          "has_waf",
    "guardduty":    "has_guardduty",
    "cloudtrail":   "has_cloudtrail",
    "s3":           "has_s3",
}


def _recommended_services(architecture: dict) -> list[str]:
    """Flatten all services from architecture layers into a list."""
    services = []
    layers = architecture.get("layers", {})
    for layer_svcs in layers.values():
        services.extend(layer_svcs)
    return services


def _normalize(name: str) -> str:
    import re
    return re.sub(r"amazon |aws ", "", name.lower()).strip()


#  Diff engine 

def _compare(recommended_services: list[str], snapshot: dict) -> list[dict]:
    """Compare recommended services to what's actually deployed.

    Returns a list of drift items, each with:
      - category: what type of drift
      - service: which service
      - severity: critical / high / medium / low
      - status: missing | misconfigured | not_deployed
      - finding: human-readable description
      - fix: what to do about it
    """
    findings = []

    for svc in recommended_services:
        norm = _normalize(svc)

        # Find the snapshot key for this service
        snapshot_key = None
        for keyword, key in _SERVICE_KEYWORDS.items():
            if keyword in norm and key:
                snapshot_key = key
                break

        if snapshot_key is None:
            continue  # service not scannable yet

        deployed = snapshot.get(snapshot_key, False)
        if isinstance(deployed, int):
            deployed = deployed > 0

        if not deployed:
            # Determine severity based on service type
            if any(k in norm for k in ["waf", "guardduty", "cloudtrail"]):
                sev = CRITICAL
                fix = f"Enable {svc} immediately — this is a security control."
            elif any(k in norm for k in ["alb", "rds", "aurora", "ecs"]):
                sev = HIGH
                fix = f"Deploy {svc} — recommended for production reliability."
            elif any(k in norm for k in ["cloudwatch", "x-ray", "xray"]):
                sev = MEDIUM
                fix = f"Set up {svc} for observability and alerting."
            else:
                sev = LOW
                fix = f"Consider adding {svc} as recommended."

            findings.append({
                "category":  "missing_service",
                "service":   svc,
                "severity":  sev,
                "status":    "not_deployed",
                "finding":   f"{svc} is recommended but not found in your AWS account.",
                "fix":       fix,
            })

    #  Configuration checks (regardless of recommendation) 

    # RDS not encrypted
    if snapshot.get("has_rds") and not snapshot.get("rds_encrypted"):
        findings.append({
            "category":  "misconfiguration",
            "service":   "Amazon RDS",
            "severity":  CRITICAL,
            "status":    "misconfigured",
            "finding":   "RDS instances found without storage encryption enabled.",
            "fix":       "Enable storage encryption on all RDS instances. For existing instances, create an encrypted snapshot and restore.",
        })

    # RDS single-AZ
    if snapshot.get("has_rds") and not snapshot.get("rds_multi_az"):
        findings.append({
            "category":  "misconfiguration",
            "service":   "Amazon RDS",
            "severity":  HIGH,
            "status":    "misconfigured",
            "finding":   "RDS is deployed in a single AZ — no automatic failover.",
            "fix":       "Enable Multi-AZ deployment on RDS instances for automatic failover (adds ~$0/month per standby).",
        })

    # EC2 single-AZ
    if snapshot.get("ec2_count", 0) > 0 and not snapshot.get("ec2_multi_az"):
        findings.append({
            "category":  "misconfiguration",
            "service":   "Amazon EC2",
            "severity":  HIGH,
            "status":    "misconfigured",
            "finding":   "EC2 instances are all in a single Availability Zone.",
            "fix":       "Spread EC2 instances across at least 2 AZs and put an ALB in front.",
        })

    # No CloudTrail
    if not snapshot.get("has_cloudtrail"):
        findings.append({
            "category":  "security_gap",
            "service":   "AWS CloudTrail",
            "severity":  CRITICAL,
            "status":    "not_deployed",
            "finding":   "CloudTrail is not enabled. All API calls are unaudited.",
            "fix":       "Enable CloudTrail with a multi-region trail and send logs to S3 with SSE-KMS encryption.",
        })

    # No GuardDuty
    if not snapshot.get("has_guardduty"):
        findings.append({
            "category":  "security_gap",
            "service":   "Amazon GuardDuty",
            "severity":  CRITICAL,
            "status":    "not_deployed",
            "finding":   "GuardDuty threat detection is not enabled.",
            "fix":       "Enable GuardDuty in all regions — it's ~$4/month for most accounts and catches credential compromise, crypto mining, and data exfiltration.",
        })

    # No CloudWatch alarms
    if not snapshot.get("has_cloudwatch_alarms"):
        findings.append({
            "category":  "observability_gap",
            "service":   "Amazon CloudWatch",
            "severity":  MEDIUM,
            "status":    "not_deployed",
            "finding":   "No CloudWatch alarms are configured. You have no alerts for failures or anomalies.",
            "fix":       "Create alarms for: CPU > 80%, error rates, latency p99, DB connections, and disk usage.",
        })

    # No WAF on public endpoints
    if snapshot.get("has_alb") or snapshot.get("has_cloudfront"):
        if not snapshot.get("has_waf"):
            findings.append({
                "category":  "security_gap",
                "service":   "AWS WAF",
                "severity":  HIGH,
                "status":    "not_deployed",
                "finding":   "Public endpoints (ALB/CloudFront) are exposed without WAF protection.",
                "fix":       "Attach AWS WAF with the AWS Managed Rules (free set) to your ALB and CloudFront distribution.",
            })

    # Sort by severity
    order = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}
    findings.sort(key=lambda x: order.get(x["severity"], 4))

    return findings


#  Drift score 

def _drift_score(findings: list[dict]) -> dict:
    """Compute an overall drift health score (0–100, higher = less drift)."""
    weights = {CRITICAL: 25, HIGH: 15, MEDIUM: 8, LOW: 3}
    penalty = sum(weights.get(f["severity"], 0) for f in findings)
    score = max(0, 100 - penalty)

    if score >= 80:
        grade, label = "A", "Well aligned"
    elif score >= 60:
        grade, label = "B", "Minor drift"
    elif score >= 40:
        grade, label = "C", "Moderate drift"
    elif score >= 20:
        grade, label = "D", "Significant drift"
    else:
        grade, label = "F", "Severely drifted"

    counts = {CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1

    return {
        "score":    score,
        "grade":    grade,
        "label":    label,
        "counts":   counts,
        "total":    len(findings),
    }


# =============================================================================
#  Azure Scanner
# =============================================================================

def _azure_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Get an Azure ARM access token using client credentials."""
    resp = _requests.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
            "scope":         "https://management.azure.com/.default",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _arm_get(token: str, subscription_id: str, path: str, api_version: str) -> list:
    """GET an Azure Resource Manager collection; returns the value list."""
    url = f"https://management.azure.com/subscriptions/{subscription_id}/{path}?api-version={api_version}"
    try:
        r = _requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        return r.json().get("value", [])
    except Exception as e:
        log.warning(f"ARM GET {path} failed: {e}")
        return []


def scan_azure_account(
    subscription_id: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    resource_group: str = "",
    region: str = "eastus",
) -> dict:
    """Scan an Azure subscription and return a service snapshot."""
    token = _azure_token(tenant_id, client_id, client_secret)
    sub   = subscription_id
    snap  = {"cloud": "azure", "region": region}

    # Compute
    vms = _arm_get(token, sub, "providers/Microsoft.Compute/virtualMachines", "2024-03-01")
    snap["vm_count"] = len(vms)
    snap["has_vms"]  = len(vms) > 0

    aks = _arm_get(token, sub, "providers/Microsoft.ContainerService/managedClusters", "2024-09-01")
    snap["has_aks"] = len(aks) > 0

    sites = _arm_get(token, sub, "providers/Microsoft.Web/sites", "2024-04-01")
    func_apps = [s for s in sites if "functionapp" in s.get("kind", "").lower()]
    snap["has_functions"]    = len(func_apps) > 0
    snap["has_app_service"]  = len(sites) > 0

    aca = _arm_get(token, sub, "providers/Microsoft.App/containerApps", "2024-03-01")
    snap["has_aca"] = len(aca) > 0

    # Databases
    sql = _arm_get(token, sub, "providers/Microsoft.Sql/servers", "2022-05-01-preview")
    snap["has_sql"]            = len(sql) > 0
    snap["sql_encrypted"]      = True  # Azure SQL always encrypts with TDE by default

    cosmos = _arm_get(token, sub, "providers/Microsoft.DocumentDB/databaseAccounts", "2024-05-15")
    snap["has_cosmos_db"] = len(cosmos) > 0

    # Caching / messaging
    redis = _arm_get(token, sub, "providers/Microsoft.Cache/redis", "2023-08-01")
    snap["has_redis"] = len(redis) > 0

    sb = _arm_get(token, sub, "providers/Microsoft.ServiceBus/namespaces", "2022-10-01-preview")
    snap["has_service_bus"] = len(sb) > 0

    eh = _arm_get(token, sub, "providers/Microsoft.EventHub/namespaces", "2024-01-01")
    snap["has_event_hubs"] = len(eh) > 0

    # Networking
    vnets = _arm_get(token, sub, "providers/Microsoft.Network/virtualNetworks", "2024-03-01")
    snap["has_vnet"] = len(vnets) > 0

    lbs = _arm_get(token, sub, "providers/Microsoft.Network/loadBalancers", "2024-03-01")
    snap["has_load_balancer"] = len(lbs) > 0

    agws = _arm_get(token, sub, "providers/Microsoft.Network/applicationGateways", "2024-03-01")
    snap["has_app_gateway"] = len(agws) > 0
    waf_gws = [gw for gw in agws if gw.get("properties", {}).get("sku", {}).get("tier", "").startswith("WAF")]
    snap["has_waf"] = len(waf_gws) > 0

    # Storage
    storage = _arm_get(token, sub, "providers/Microsoft.Storage/storageAccounts", "2023-05-01")
    snap["has_blob_storage"] = len(storage) > 0

    # Security
    kv = _arm_get(token, sub, "providers/Microsoft.KeyVault/vaults", "2022-07-01")
    snap["has_key_vault"] = len(kv) > 0

    pricings = _arm_get(token, sub, "providers/Microsoft.Security/pricings", "2024-01-01")
    active_defender = [p for p in pricings if p.get("properties", {}).get("pricingTier") != "Free"]
    snap["has_defender"] = len(active_defender) > 0

    # Monitoring
    ws = _arm_get(token, sub, "providers/Microsoft.OperationalInsights/workspaces", "2023-09-01")
    snap["has_log_analytics"] = len(ws) > 0

    return snap


def _compare_azure(recommended_services: list[str], snapshot: dict) -> list[dict]:
    """Compare recommended Azure services to what's actually deployed."""
    findings = []

    _AZURE_KEYWORDS = {
        "aks":                        ("has_aks",           HIGH,     "Azure Kubernetes Service (AKS) is recommended but not found."),
        "azure kubernetes":            ("has_aks",           HIGH,     "Azure Kubernetes Service (AKS) is recommended but not found."),
        "azure functions":             ("has_functions",     MEDIUM,   "Azure Functions is recommended but no Function Apps found."),
        "container apps":              ("has_aca",           MEDIUM,   "Azure Container Apps is recommended but not deployed."),
        "azure sql":                   ("has_sql",           HIGH,     "Azure SQL Database is recommended but no SQL servers found."),
        "sql server":                  ("has_sql",           HIGH,     "Azure SQL Database is recommended but no SQL servers found."),
        "cosmos db":                   ("has_cosmos_db",     MEDIUM,   "Cosmos DB is recommended but not deployed."),
        "azure cache for redis":       ("has_redis",         MEDIUM,   "Azure Cache for Redis is recommended but not deployed."),
        "redis":                       ("has_redis",         MEDIUM,   "Azure Cache for Redis is recommended but not deployed."),
        "service bus":                 ("has_service_bus",   MEDIUM,   "Azure Service Bus is recommended but no namespaces found."),
        "event hubs":                  ("has_event_hubs",    MEDIUM,   "Azure Event Hubs is recommended but not deployed."),
        "application gateway":         ("has_app_gateway",   HIGH,     "Azure Application Gateway is recommended but not deployed."),
        "load balancer":               ("has_load_balancer", HIGH,     "Azure Load Balancer is recommended but not deployed."),
        "blob storage":                ("has_blob_storage",  MEDIUM,   "Azure Blob Storage is recommended but no storage accounts found."),
        "key vault":                   ("has_key_vault",     CRITICAL, "Azure Key Vault is recommended but not deployed — secrets may be exposed."),
        "defender for cloud":          ("has_defender",      CRITICAL, "Microsoft Defender for Cloud is not active — threat detection gap."),
        "log analytics":               ("has_log_analytics", MEDIUM,   "Azure Monitor Log Analytics is recommended but no workspaces found."),
        "azure monitor":               ("has_log_analytics", MEDIUM,   "Azure Monitor is recommended but no workspaces found."),
        "waf":                         ("has_waf",           HIGH,     "Azure WAF (Application Gateway WAF) is recommended but not configured."),
        "virtual network":             ("has_vnet",          HIGH,     "Azure Virtual Network is recommended but no VNets found."),
        "vnet":                        ("has_vnet",          HIGH,     "Azure Virtual Network is recommended but no VNets found."),
    }

    for svc in recommended_services:
        norm = svc.lower()
        for keyword, (snap_key, sev, finding_text) in _AZURE_KEYWORDS.items():
            if keyword in norm:
                if not snapshot.get(snap_key, False):
                    findings.append({
                        "category": "missing_service",
                        "service":  svc,
                        "severity": sev,
                        "status":   "not_deployed",
                        "finding":  finding_text,
                        "fix":      f"Deploy {svc} in your Azure subscription.",
                    })
                break  # one finding per service

    # Security checks regardless of recommendation
    if not snapshot.get("has_key_vault"):
        findings.append({
            "category": "security_gap",
            "service":  "Azure Key Vault",
            "severity": CRITICAL,
            "status":   "not_deployed",
            "finding":  "No Key Vault found — secrets, keys, and certificates may be stored insecurely.",
            "fix":      "Create an Azure Key Vault and migrate all secrets/connection strings to it.",
        })

    if not snapshot.get("has_defender"):
        findings.append({
            "category": "security_gap",
            "service":  "Microsoft Defender for Cloud",
            "severity": CRITICAL,
            "status":   "not_deployed",
            "finding":  "Microsoft Defender for Cloud has no paid plans active — threat detection is minimal.",
            "fix":      "Enable Defender for Cloud plans for Servers, Storage, SQL, and Containers.",
        })

    if not snapshot.get("has_waf") and (snapshot.get("has_app_gateway") or snapshot.get("has_load_balancer")):
        findings.append({
            "category": "security_gap",
            "service":  "Azure WAF",
            "severity": HIGH,
            "status":   "misconfigured",
            "finding":  "Public endpoints exist without WAF protection.",
            "fix":      "Enable WAF_v2 tier on your Application Gateway or use Azure Front Door with WAF policy.",
        })

    if not snapshot.get("has_log_analytics"):
        findings.append({
            "category": "observability_gap",
            "service":  "Azure Monitor Log Analytics",
            "severity": MEDIUM,
            "status":   "not_deployed",
            "finding":  "No Log Analytics workspace found — limited observability.",
            "fix":      "Create a Log Analytics workspace and connect all resources to it.",
        })

    order = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}
    findings.sort(key=lambda x: order.get(x["severity"], 4))
    return findings


# =============================================================================
#  GCP Scanner
# =============================================================================

def _gcp_token(service_account_json: str) -> str:
    """Get a GCP access token using a service account JSON key (RSA JWT flow)."""
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    sa  = json.loads(service_account_json)
    now = int(time.time())

    header  = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({
        "iss":   sa["client_email"],
        "scope": "https://www.googleapis.com/auth/cloud-platform",
        "aud":   "https://oauth2.googleapis.com/token",
        "exp":   now + 3600,
        "iat":   now,
    }).encode()).rstrip(b"=").decode()

    to_sign = f"{header}.{payload}".encode()
    private_key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = private_key.sign(to_sign, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()

    jwt = f"{header}.{payload}.{sig_b64}"
    resp = _requests.post(
        "https://oauth2.googleapis.com/token",
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _gcp_get(token: str, url: str) -> dict:
    """GET a GCP REST API endpoint; returns the parsed JSON or {}."""
    try:
        r = _requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        return r.json()
    except Exception as e:
        log.warning(f"GCP GET {url} failed: {e}")
        return {}


def scan_gcp_account(project_id: str, service_account_json: str, region: str = "us-central1") -> dict:
    """Scan a GCP project and return a service snapshot."""
    token = _gcp_token(service_account_json)
    snap  = {"cloud": "gcp", "region": region}
    base  = f"https://compute.googleapis.com/compute/v1/projects/{project_id}"

    # Compute — VM instances
    agg = _gcp_get(token, f"{base}/aggregated/instances")
    instances = []
    for zone_data in agg.get("items", {}).values():
        instances.extend(zone_data.get("instances", []))
    snap["vm_count"] = len(instances)
    snap["has_vms"]  = len(instances) > 0

    # GKE clusters
    gke = _gcp_get(token, f"https://container.googleapis.com/v1/projects/{project_id}/locations/-/clusters")
    clusters = gke.get("clusters", [])
    snap["has_gke"] = len(clusters) > 0

    # Cloud Run services
    run = _gcp_get(token, f"https://run.googleapis.com/v2/projects/{project_id}/locations/-/services")
    snap["has_cloud_run"] = len(run.get("services", [])) > 0

    # Cloud Functions
    funcs = _gcp_get(token, f"https://cloudfunctions.googleapis.com/v2/projects/{project_id}/locations/-/functions")
    snap["has_cloud_functions"] = len(funcs.get("functions", [])) > 0

    # Cloud SQL
    sql = _gcp_get(token, f"https://sqladmin.googleapis.com/v1/projects/{project_id}/instances")
    sql_instances = sql.get("items", [])
    snap["has_cloud_sql"] = len(sql_instances) > 0
    snap["sql_encrypted"] = all(
        i.get("diskEncryptionConfiguration") or i.get("settings", {}).get("dataDiskType")
        for i in sql_instances
    ) if sql_instances else False

    # Pub/Sub
    topics = _gcp_get(token, f"https://pubsub.googleapis.com/v1/projects/{project_id}/topics")
    snap["has_pubsub"] = len(topics.get("topics", [])) > 0

    # Cloud Storage
    buckets = _gcp_get(token, f"https://storage.googleapis.com/storage/v1/b?project={project_id}")
    snap["has_cloud_storage"] = len(buckets.get("items", [])) > 0

    # Secret Manager
    secrets = _gcp_get(token, f"https://secretmanager.googleapis.com/v1/projects/{project_id}/secrets")
    snap["has_secret_manager"] = len(secrets.get("secrets", [])) > 0

    # Cloud KMS key rings
    kms = _gcp_get(token, f"https://cloudkms.googleapis.com/v1/projects/{project_id}/locations/-/keyRings")
    snap["has_kms"] = len(kms.get("keyRings", [])) > 0

    # BigQuery datasets
    bq = _gcp_get(token, f"https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/datasets")
    snap["has_bigquery"] = len(bq.get("datasets", [])) > 0

    # Cloud Load Balancers (forwarding rules as proxy)
    fwr = _gcp_get(token, f"{base}/global/forwardingRules")
    snap["has_load_balancer"] = len(fwr.get("items", [])) > 0

    # Cloud Armor security policies
    armor = _gcp_get(token, f"{base}/global/securityPolicies")
    snap["has_cloud_armor"] = len(armor.get("items", [])) > 0

    # Cloud Monitoring alert policies
    alert = _gcp_get(token, f"https://monitoring.googleapis.com/v3/projects/{project_id}/alertPolicies")
    snap["has_monitoring_alerts"] = len(alert.get("alertPolicies", [])) > 0

    return snap


def _compare_gcp(recommended_services: list[str], snapshot: dict) -> list[dict]:
    """Compare recommended GCP services to what's actually deployed."""
    findings = []

    _GCP_KEYWORDS = {
        "gke":                  ("has_gke",              HIGH,     "GKE cluster is recommended but not found."),
        "google kubernetes":    ("has_gke",              HIGH,     "GKE cluster is recommended but not found."),
        "cloud run":            ("has_cloud_run",        MEDIUM,   "Cloud Run is recommended but no services deployed."),
        "cloud functions":      ("has_cloud_functions",  MEDIUM,   "Cloud Functions is recommended but no functions deployed."),
        "cloud sql":            ("has_cloud_sql",        HIGH,     "Cloud SQL is recommended but no instances found."),
        "cloud spanner":        ("has_cloud_sql",        MEDIUM,   "Cloud Spanner is recommended — consider migrating from Cloud SQL."),
        "pub/sub":              ("has_pubsub",           MEDIUM,   "Pub/Sub is recommended but no topics found."),
        "pubsub":               ("has_pubsub",           MEDIUM,   "Pub/Sub is recommended but no topics found."),
        "cloud storage":        ("has_cloud_storage",    MEDIUM,   "Cloud Storage is recommended but no buckets found."),
        "gcs":                  ("has_cloud_storage",    MEDIUM,   "Cloud Storage (GCS) is recommended but no buckets found."),
        "secret manager":       ("has_secret_manager",   CRITICAL, "Secret Manager is recommended — secrets may be stored insecurely."),
        "cloud kms":            ("has_kms",              CRITICAL, "Cloud KMS is recommended but no key rings found — CMEK not active."),
        "kms":                  ("has_kms",              CRITICAL, "Cloud KMS is recommended but no key rings found — CMEK not active."),
        "bigquery":             ("has_bigquery",         MEDIUM,   "BigQuery is recommended but no datasets found."),
        "cloud armor":          ("has_cloud_armor",      HIGH,     "Cloud Armor WAF is recommended but no security policies found."),
        "cloud load balancing": ("has_load_balancer",    HIGH,     "Cloud Load Balancing is recommended but no forwarding rules found."),
        "cloud monitoring":     ("has_monitoring_alerts",MEDIUM,   "Cloud Monitoring alerts are recommended but none configured."),
    }

    for svc in recommended_services:
        norm = svc.lower()
        for keyword, (snap_key, sev, finding_text) in _GCP_KEYWORDS.items():
            if keyword in norm:
                if not snapshot.get(snap_key, False):
                    findings.append({
                        "category": "missing_service",
                        "service":  svc,
                        "severity": sev,
                        "status":   "not_deployed",
                        "finding":  finding_text,
                        "fix":      f"Deploy {svc} in your GCP project.",
                    })
                break

    # Security checks regardless of recommendation
    if not snapshot.get("has_secret_manager"):
        findings.append({
            "category": "security_gap",
            "service":  "Secret Manager",
            "severity": CRITICAL,
            "status":   "not_deployed",
            "finding":  "No Secret Manager secrets found — credentials may be stored in environment variables or source code.",
            "fix":      "Enable Secret Manager API and migrate all secrets to it.",
        })

    if not snapshot.get("has_kms"):
        findings.append({
            "category": "security_gap",
            "service":  "Cloud KMS",
            "severity": CRITICAL,
            "status":   "not_deployed",
            "finding":  "No Cloud KMS key rings found — customer-managed encryption keys (CMEK) are not active.",
            "fix":      "Create Cloud KMS key rings and enable CMEK on Cloud SQL, Cloud Storage, and Pub/Sub.",
        })

    if not snapshot.get("has_cloud_armor"):
        findings.append({
            "category": "security_gap",
            "service":  "Cloud Armor",
            "severity": HIGH,
            "status":   "not_deployed",
            "finding":  "No Cloud Armor security policies found — public endpoints have no WAF protection.",
            "fix":      "Create a Cloud Armor security policy with OWASP Core Rule Set and attach it to your backend services.",
        })

    if not snapshot.get("has_monitoring_alerts"):
        findings.append({
            "category": "observability_gap",
            "service":  "Cloud Monitoring",
            "severity": MEDIUM,
            "status":   "not_deployed",
            "finding":  "No Cloud Monitoring alert policies configured — no automated incident detection.",
            "fix":      "Create alert policies for error rates, latency p99, and resource utilization.",
        })

    order = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}
    findings.sort(key=lambda x: order.get(x["severity"], 4))
    return findings


# =============================================================================
#  Main entrypoint
# =============================================================================

def scan_and_compare(
    recommended: dict,
    cloud_provider: str = "aws",
    aws_access_key_id: str = "",
    aws_secret_access_key: str = "",
    region: str = "us-east-1",
    # Azure
    subscription_id: str = "",
    tenant_id: str = "",
    client_id: str = "",
    client_secret: str = "",
    resource_group: str = "",
    # GCP
    project_id: str = "",
    service_account_json: str = "",
) -> dict:
    """Scan a cloud account and compare to the recommended architecture.

    Routes to the correct scanner based on cloud_provider ('aws', 'azure', 'gcp').
    Returns a full drift report dict.
    """
    cloud = (cloud_provider or "aws").lower()
    rec_services = _recommended_services(recommended)

    if cloud == "azure":
        log.info(f"Scanning Azure subscription {subscription_id}...")
        snapshot = scan_azure_account(subscription_id, tenant_id, client_id, client_secret, resource_group, region)
        findings = _compare_azure(rec_services, snapshot)
    elif cloud == "gcp":
        log.info(f"Scanning GCP project {project_id}...")
        snapshot = scan_gcp_account(project_id, service_account_json, region)
        findings = _compare_gcp(rec_services, snapshot)
    else:
        log.info(f"Scanning AWS account in {region}...")
        snapshot = scan_aws_account(aws_access_key_id, aws_secret_access_key, region)
        findings = _compare(rec_services, snapshot)

    score = _drift_score(findings)
    log.info(f"Drift score: {score['score']} ({score['grade']}) — {len(findings)} findings")

    return {
        "cloud_provider": cloud,
        "region":         region,
        "snapshot":       snapshot,
        "findings":       findings,
        "score":          score,
    }


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    mock_recommended = {
        "layers": {
            "edge":       ["Amazon CloudFront"],
            "networking": ["Application Load Balancer", "Amazon API Gateway"],
            "compute":    ["Amazon ECS", "AWS Lambda"],
            "database":   ["Amazon RDS", "Amazon DynamoDB"],
            "messaging":  ["Amazon SQS"],
            "monitoring": ["Amazon CloudWatch", "AWS X-Ray"],
        }
    }

    report = scan_and_compare(
        recommended=mock_recommended,
        cloud_provider="aws",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        region=os.getenv("AWS_REGION", "us-east-1"),
    )
    print(json.dumps(report, indent=2))
