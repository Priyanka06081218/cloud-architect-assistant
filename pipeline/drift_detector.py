# pipeline/drift_detector.py
#
# Architecture Drift Detector
#
# Scans a real AWS account via boto3 and compares what's actually deployed
# against what the pipeline recommended. Produces a drift report with
# severity-scored gaps and fix suggestions.
#
# Usage:
#   from pipeline.drift_detector import scan_and_compare
#   report = scan_and_compare(
#       recommended=architecture_dict,   # from run_pipeline()
#       aws_access_key_id="...",
#       aws_secret_access_key="...",
#       region="us-east-1",
#   )

import logging
from typing import Optional

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


#  Main entrypoint 

def scan_and_compare(
    recommended: dict,
    aws_access_key_id: str,
    aws_secret_access_key: str,
    region: str = "us-east-1",
) -> dict:
    """Scan AWS account and compare to recommended architecture.

    Args:
        recommended:           architecture dict from run_pipeline() (the 'architecture' key)
        aws_access_key_id:     AWS access key (read-only IAM recommended)
        aws_secret_access_key: AWS secret key
        region:                AWS region to scan

    Returns full drift report dict.
    """
    log.info(f"Scanning AWS account in {region}...")
    snapshot = scan_aws_account(aws_access_key_id, aws_secret_access_key, region)
    log.info(f"Scan complete. Found: {snapshot}")

    rec_services = _recommended_services(recommended)
    log.info(f"Recommended services: {rec_services}")

    findings = _compare(rec_services, snapshot)
    score    = _drift_score(findings)

    log.info(f"Drift score: {score['score']} ({score['grade']}) — {len(findings)} findings")

    return {
        "region":    region,
        "snapshot":  snapshot,
        "findings":  findings,
        "score":     score,
    }


if __name__ == "__main__":
    import json, os
    from dotenv import load_dotenv
    load_dotenv()

    # Quick test — reads credentials from .env
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
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        region=os.getenv("AWS_REGION", "us-east-1"),
    )
    print(json.dumps(report, indent=2))
