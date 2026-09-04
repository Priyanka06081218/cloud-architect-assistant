"use client";

import { useState } from "react";

// ─── Types ───────────────────────────────────────────────────────────────────

interface DriftFinding {
  category: string;
  service: string;
  severity: "critical" | "high" | "medium" | "low";
  status: string;
  finding: string;
  fix: string;
}

interface DriftScore {
  score: number;
  grade: string;
  label: string;
  counts: Record<string, number>;
  total: number;
}

interface DriftReport {
  region: string;
  snapshot: Record<string, unknown>;
  findings: DriftFinding[];
  score: DriftScore;
  elapsed_seconds?: number;
}

interface DriftTabProps {
  architecture: Record<string, unknown>;
}

type CloudProvider = "aws" | "azure" | "gcp";

// ─── Severity styles ─────────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border border-red-300",
  high:     "bg-orange-100 text-orange-800 border border-orange-300",
  medium:   "bg-yellow-100 text-yellow-700 border border-yellow-300",
  low:      "bg-blue-100 text-blue-700 border border-blue-300",
};

const GRADE_COLOUR: Record<string, string> = {
  A: "text-green-600",
  B: "text-lime-600",
  C: "text-yellow-600",
  D: "text-orange-600",
  F: "text-red-600",
};

// ─── Cloud tab config ─────────────────────────────────────────────────────────

const CLOUD_TABS: { id: CloudProvider; label: string; color: string; badge: string }[] = [
  { id: "aws",   label: "AWS",   color: "bg-yellow-50 border-yellow-400 text-yellow-800", badge: "bg-yellow-100 text-yellow-700" },
  { id: "azure", label: "Azure", color: "bg-blue-50 border-blue-400 text-blue-800",       badge: "bg-blue-100 text-blue-700"    },
  { id: "gcp",   label: "GCP",   color: "bg-green-50 border-green-400 text-green-800",    badge: "bg-green-100 text-green-700"  },
];

// ─── Score gauge ──────────────────────────────────────────────────────────────

function ScoreGauge({ score }: { score: DriftScore }) {
  const pct = score.score;
  const colour =
    pct >= 80 ? "#16a34a" : pct >= 60 ? "#65a30d" : pct >= 40 ? "#ca8a04" : "#dc2626";

  return (
    <div className="flex items-center gap-6">
      <div className="relative w-24 h-24 flex-shrink-0">
        <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
          <circle cx="18" cy="18" r="15.9" fill="none" stroke="#e5e7eb" strokeWidth="3" />
          <circle
            cx="18" cy="18" r="15.9" fill="none" stroke={colour} strokeWidth="3"
            strokeDasharray={`${pct} ${100 - pct}`} strokeLinecap="round"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={`text-2xl font-bold ${GRADE_COLOUR[score.grade] ?? "text-gray-800"}`}>
            {score.grade}
          </span>
          <span className="text-xs text-gray-500">{pct}/100</span>
        </div>
      </div>
      <div>
        <p className="text-lg font-semibold text-gray-800">{score.label}</p>
        <p className="text-sm text-gray-500 mb-2">{score.total} issue{score.total !== 1 ? "s" : ""} found</p>
        <div className="flex gap-3 flex-wrap">
          {(["critical", "high", "medium", "low"] as const).map((s) =>
            (score.counts[s] ?? 0) > 0 ? (
              <span key={s} className={`text-xs font-medium px-2 py-0.5 rounded-full ${SEVERITY_STYLES[s]}`}>
                {score.counts[s]} {s}
              </span>
            ) : null
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Finding card ─────────────────────────────────────────────────────────────

function FindingCard({ f }: { f: DriftFinding }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      className="border rounded-lg p-4 hover:shadow-sm transition-shadow cursor-pointer bg-white"
      onClick={() => setExpanded((x) => !x)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="font-medium text-gray-800 text-sm leading-snug">{f.finding}</p>
          <p className="text-xs text-gray-400 mt-1">{f.service}</p>
        </div>
        <span className={`flex-shrink-0 text-xs font-semibold uppercase px-2 py-0.5 rounded-full ${SEVERITY_STYLES[f.severity]}`}>
          {f.severity}
        </span>
      </div>
      {expanded && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">How to fix</p>
          <p className="text-sm text-gray-700">{f.fix}</p>
        </div>
      )}
    </div>
  );
}

// ─── Snapshot panel (AWS) ─────────────────────────────────────────────────────

function SnapshotPanel({ snapshot, cloud }: { snapshot: Record<string, unknown>; cloud: CloudProvider }) {
  const AWS_ICONS: Record<string, string> = {
    ec2_count: "EC2", has_ecs: "ECS", has_lambda: "Lambda", has_rds: "RDS",
    has_dynamodb: "DynamoDB", has_elasticache: "ElastiCache", has_alb: "ALB",
    has_cloudfront: "CloudFront", has_sqs: "SQS", has_api_gateway: "API Gateway",
    has_cloudwatch_alarms: "CloudWatch", has_cloudtrail: "CloudTrail",
    has_guardduty: "GuardDuty", has_waf: "WAF", has_s3: "S3",
  };
  const AZURE_ICONS: Record<string, string> = {
    has_vms: "Virtual Machines", has_aks: "AKS", has_aca: "Container Apps",
    has_functions: "Azure Functions", has_sql: "Azure SQL", has_cosmos_db: "Cosmos DB",
    has_redis: "Azure Redis", has_service_bus: "Service Bus", has_app_gateway: "App Gateway",
    has_waf: "WAF", has_log_analytics: "Log Analytics", has_key_vault: "Key Vault",
    has_defender: "Defender for Cloud", has_blob_storage: "Blob Storage",
  };
  const GCP_ICONS: Record<string, string> = {
    has_vms: "Compute VMs", has_gke: "GKE", has_cloud_run: "Cloud Run",
    has_cloud_functions: "Cloud Functions", has_cloud_sql: "Cloud SQL",
    has_pubsub: "Pub/Sub", has_cloud_storage: "Cloud Storage",
    has_load_balancer: "Cloud LB", has_cloud_armor: "Cloud Armor",
    has_monitoring_alerts: "Cloud Monitoring", has_kms: "Cloud KMS",
    has_secret_manager: "Secret Manager", has_bigquery: "BigQuery",
  };

  const icons = cloud === "aws" ? AWS_ICONS : cloud === "azure" ? AZURE_ICONS : GCP_ICONS;

  return (
    <div>
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        What&rsquo;s deployed in your account
      </p>
      <div className="grid grid-cols-3 gap-2">
        {Object.entries(icons).map(([key, label]) => {
          const val = snapshot[key];
          const active = typeof val === "boolean" ? val : typeof val === "number" ? val > 0 : false;
          const count = typeof val === "number" ? val : undefined;
          return (
            <div
              key={key}
              className={`flex items-center gap-2 text-xs px-2 py-1.5 rounded-md border ${
                active ? "bg-green-50 border-green-200 text-green-800" : "bg-gray-50 border-gray-200 text-gray-400"
              }`}
            >
              <span>{active ? "yes" : "no"}</span>
              <span className="font-medium truncate">
                {label}{count !== undefined && count > 0 ? ` (${count})` : ""}
              </span>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-gray-400 mt-2">
        Region / location: {String(snapshot.region ?? snapshot.location ?? "unknown")}
      </p>
    </div>
  );
}

// ─── Credential forms ─────────────────────────────────────────────────────────

function AWSForm({
  onScan, loading,
}: {
  onScan: (creds: Record<string, string>) => void;
  loading: boolean;
}) {
  const [keyId, setKeyId] = useState("");
  const [secret, setSecret] = useState("");
  const [region, setRegion] = useState("us-east-1");

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-gray-700 mb-1">AWS Credentials</p>
        <p className="text-xs text-gray-500">
          Create a read-only IAM user with <code className="bg-gray-100 px-1 rounded">ReadOnlyAccess</code> policy.
          Credentials are never stored or logged.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Access Key ID</label>
          <input
            type="text" placeholder="AKIAIOSFODNN7EXAMPLE" value={keyId}
            onChange={(e) => setKeyId(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Secret Access Key</label>
          <input
            type="password" placeholder="wJalrXUtnFEMI..." value={secret}
            onChange={(e) => setSecret(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">Region</label>
          <select
            value={region} onChange={(e) => setRegion(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {["us-east-1","us-east-2","us-west-1","us-west-2","eu-west-1","eu-west-2",
              "eu-central-1","ap-south-1","ap-southeast-1","ap-southeast-2","ap-northeast-1"].map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
        <button
          onClick={() => onScan({ aws_access_key_id: keyId, aws_secret_access_key: secret, region })}
          disabled={loading || !keyId || !secret}
          className="px-5 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Scanning..." : "Run Drift Scan"}
        </button>
      </div>
    </div>
  );
}

function AzureForm({
  onScan, loading,
}: {
  onScan: (creds: Record<string, string>) => void;
  loading: boolean;
}) {
  const [subscriptionId, setSubscriptionId] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [resourceGroup, setResourceGroup] = useState("");

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-gray-700 mb-1">Azure Credentials</p>
        <p className="text-xs text-gray-500">
          Create an App Registration with the <code className="bg-gray-100 px-1 rounded">Reader</code> role on your subscription.
          Credentials are never stored or logged.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Subscription ID</label>
          <input
            type="text" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" value={subscriptionId}
            onChange={(e) => setSubscriptionId(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Tenant ID</label>
          <input
            type="text" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Client ID (App Registration)</label>
          <input
            type="text" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Client Secret</label>
          <input
            type="password" placeholder="your-client-secret" value={clientSecret}
            onChange={(e) => setClientSecret(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Resource Group <span className="text-gray-400">(optional -- scans all if blank)</span>
          </label>
          <input
            type="text" placeholder="my-resource-group" value={resourceGroup}
            onChange={(e) => setResourceGroup(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <button
          onClick={() => onScan({
            subscription_id: subscriptionId,
            tenant_id: tenantId,
            client_id: clientId,
            client_secret: clientSecret,
            resource_group: resourceGroup,
          })}
          disabled={loading || !subscriptionId || !tenantId || !clientId || !clientSecret}
          className="px-5 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Scanning..." : "Run Drift Scan"}
        </button>
      </div>
    </div>
  );
}

function GCPForm({
  onScan, loading,
}: {
  onScan: (creds: Record<string, string>) => void;
  loading: boolean;
}) {
  const [projectId, setProjectId] = useState("");
  const [saJson, setSaJson] = useState("");
  const [gcpRegion, setGcpRegion] = useState("us-central1");

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-gray-700 mb-1">GCP Credentials</p>
        <p className="text-xs text-gray-500">
          Create a service account with the <code className="bg-gray-100 px-1 rounded">roles/viewer</code> role and paste its JSON key below.
          Credentials are never stored or logged.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Project ID</label>
          <input
            type="text" placeholder="my-gcp-project-123" value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Region</label>
          <select
            value={gcpRegion} onChange={(e) => setGcpRegion(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {["us-central1","us-east1","us-west1","us-west2","europe-west1","europe-west2",
              "asia-east1","asia-southeast1","asia-northeast1"].map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Service Account JSON Key</label>
        <textarea
          rows={6}
          placeholder={`{\n  "type": "service_account",\n  "project_id": "my-project",\n  ...\n}`}
          value={saJson}
          onChange={(e) => setSaJson(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
      </div>
      <div className="flex justify-end">
        <button
          onClick={() => onScan({
            project_id: projectId,
            service_account_json: saJson,
            region: gcpRegion,
          })}
          disabled={loading || !projectId || !saJson}
          className="px-5 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Scanning..." : "Run Drift Scan"}
        </button>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DriftTab({ architecture }: DriftTabProps) {
  const [cloud, setCloud]           = useState<CloudProvider>("aws");
  const [loading, setLoading]       = useState(false);
  const [report, setReport]         = useState<DriftReport | null>(null);
  const [error, setError]           = useState<string | null>(null);
  const [activeFilter, setFilter]   = useState<string>("all");

  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  async function runScan(creds: Record<string, string>) {
    setLoading(true);
    setError(null);
    setReport(null);

    try {
      const res = await fetch(`${apiBase}/drift`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ architecture, cloud_provider: cloud, ...creds }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }

      const data: DriftReport = await res.json();
      setReport(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setLoading(false);
    }
  }

  const filteredFindings =
    report?.findings.filter((f) => activeFilter === "all" || f.severity === activeFilter) ?? [];

  const activeTab = CLOUD_TABS.find((t) => t.id === cloud)!;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-gray-800">Architecture Drift Detection</h2>
        <p className="text-sm text-gray-500 mt-1">
          Connect your cloud account to compare what&rsquo;s deployed against the recommended architecture.
          Uses read-only API calls -- no changes are made.
        </p>
      </div>

      {/* Cloud selector tabs */}
      <div className="flex gap-2">
        {CLOUD_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => { setCloud(tab.id); setReport(null); setError(null); }}
            className={`
              px-5 py-2 rounded-lg border-2 text-sm font-semibold transition-all
              ${cloud === tab.id
                ? tab.color + " shadow-sm"
                : "border-gray-200 bg-white text-gray-500 hover:border-gray-300"
              }
            `}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Credential form */}
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-5">
        {cloud === "aws"   && <AWSForm   onScan={runScan} loading={loading} />}
        {cloud === "azure" && <AzureForm onScan={runScan} loading={loading} />}
        {cloud === "gcp"   && <GCPForm   onScan={runScan} loading={loading} />}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex flex-col items-center py-10 gap-3 text-gray-500">
          <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-sm">
            Scanning {activeTab.label} account... this takes 5-10 seconds
          </p>
        </div>
      )}

      {/* Report */}
      {report && !loading && (
        <div className="space-y-6">
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <ScoreGauge score={report.score} />
            {report.elapsed_seconds && (
              <p className="text-xs text-gray-400 mt-3">Scan completed in {report.elapsed_seconds}s</p>
            )}
          </div>

          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <SnapshotPanel snapshot={report.snapshot} cloud={cloud} />
          </div>

          {report.findings.length > 0 ? (
            <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <p className="font-semibold text-gray-800">
                  {report.findings.length} Drift Finding{report.findings.length !== 1 ? "s" : ""}
                </p>
                <div className="flex gap-2 flex-wrap">
                  {(["all", "critical", "high", "medium", "low"] as const).map((s) => (
                    <button
                      key={s}
                      onClick={() => setFilter(s)}
                      className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                        activeFilter === s
                          ? "bg-blue-600 text-white border-blue-600"
                          : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
                      }`}
                    >
                      {s === "all" ? "All" : s}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                {filteredFindings.length === 0 ? (
                  <p className="text-sm text-gray-400 text-center py-4">No {activeFilter} findings.</p>
                ) : (
                  filteredFindings.map((f, i) => <FindingCard key={i} f={f} />)
                )}
              </div>
            </div>
          ) : (
            <div className="bg-green-50 border border-green-200 rounded-xl p-5 text-center">
              <p className="text-green-800 font-semibold">No drift detected!</p>
              <p className="text-sm text-green-600 mt-1">
                Your deployed infrastructure matches all the recommendations.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
