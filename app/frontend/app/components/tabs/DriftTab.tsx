"use client";

import { useState } from "react";

//  Types 

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
  architecture: Record<string, unknown>; // architecture.layers from /analyze
}

//  Severity colours 

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border border-red-300",
  high:     "bg-orange-100 text-orange-800 border border-orange-300",
  medium:   "bg-yellow-100 text-yellow-700 border border-yellow-300",
  low:      "bg-blue-100 text-blue-700 border border-blue-300",
};

const SEVERITY_ICON: Record<string, string> = {
  critical: "",
  high:     "",
  medium:   "",
  low:      "",
};

const GRADE_COLOUR: Record<string, string> = {
  A: "text-green-600",
  B: "text-lime-600",
  C: "text-yellow-600",
  D: "text-orange-600",
  F: "text-red-600",
};

//  Score gauge 

function ScoreGauge({ score }: { score: DriftScore }) {
  const pct = score.score;
  const colour =
    pct >= 80 ? "#16a34a" : pct >= 60 ? "#65a30d" : pct >= 40 ? "#ca8a04" : "#dc2626";

  return (
    <div className="flex items-center gap-6">
      {/* Circular gauge */}
      <div className="relative w-24 h-24 flex-shrink-0">
        <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
          <circle
            cx="18" cy="18" r="15.9"
            fill="none"
            stroke="#e5e7eb"
            strokeWidth="3"
          />
          <circle
            cx="18" cy="18" r="15.9"
            fill="none"
            stroke={colour}
            strokeWidth="3"
            strokeDasharray={`${pct} ${100 - pct}`}
            strokeLinecap="round"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={`text-2xl font-bold ${GRADE_COLOUR[score.grade] ?? "text-gray-800"}`}>
            {score.grade}
          </span>
          <span className="text-xs text-gray-500">{pct}/100</span>
        </div>
      </div>

      {/* Counts */}
      <div>
        <p className="text-lg font-semibold text-gray-800">{score.label}</p>
        <p className="text-sm text-gray-500 mb-2">{score.total} issue{score.total !== 1 ? "s" : ""} found</p>
        <div className="flex gap-3 flex-wrap">
          {(["critical", "high", "medium", "low"] as const).map((s) =>
            (score.counts[s] ?? 0) > 0 ? (
              <span
                key={s}
                className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${SEVERITY_STYLES[s]}`}
              >
                {SEVERITY_ICON[s]} {score.counts[s]} {s}
              </span>
            ) : null
          )}
        </div>
      </div>
    </div>
  );
}

//  Finding card 

function FindingCard({ f }: { f: DriftFinding }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className="border rounded-lg p-4 hover:shadow-sm transition-shadow cursor-pointer bg-white"
      onClick={() => setExpanded((x) => !x)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <span className="text-lg mt-0.5">{SEVERITY_ICON[f.severity]}</span>
          <div className="min-w-0">
            <p className="font-medium text-gray-800 text-sm leading-snug">{f.finding}</p>
            <p className="text-xs text-gray-400 mt-1">{f.service}</p>
          </div>
        </div>
        <span
          className={`flex-shrink-0 text-xs font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full ${SEVERITY_STYLES[f.severity]}`}
        >
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

//  Snapshot panel 

function SnapshotPanel({ snapshot }: { snapshot: Record<string, unknown> }) {
  const SERVICE_ICONS: Record<string, string> = {
    ec2_count:               "EC2",
    has_ecs:                 "ECS",
    has_lambda:              "Lambda",
    has_rds:                 "RDS",
    has_dynamodb:            "DynamoDB",
    has_elasticache:         "ElastiCache",
    has_alb:                 "ALB",
    has_cloudfront:          "CloudFront",
    has_sqs:                 "SQS",
    has_api_gateway:         "API Gateway",
    has_cloudwatch_alarms:   "CloudWatch",
    has_cloudtrail:          "CloudTrail",
    has_guardduty:           "GuardDuty",
    has_waf:                 "WAF",
    has_s3:                  "S3",
  };

  return (
    <div>
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">What&rsquo;s deployed in your account</p>
      <div className="grid grid-cols-3 gap-2">
        {Object.entries(SERVICE_ICONS).map(([key, label]) => {
          const val = snapshot[key];
          const active =
            typeof val === "boolean" ? val : typeof val === "number" ? val > 0 : false;
          const count = typeof val === "number" ? val : undefined;

          return (
            <div
              key={key}
              className={`flex items-center gap-2 text-xs px-2 py-1.5 rounded-md border ${
                active
                  ? "bg-green-50 border-green-200 text-green-800"
                  : "bg-gray-50 border-gray-200 text-gray-400"
              }`}
            >
              <span>{active ? "yes" : "no"}</span>
              <span className="font-medium truncate">
                {label}
                {count !== undefined && count > 0 ? ` (${count})` : ""}
              </span>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-gray-400 mt-2">Region: {String(snapshot.region ?? "us-east-1")}</p>
    </div>
  );
}

//  Main component 

export default function DriftTab({ architecture }: DriftTabProps) {
  const [keyId, setKeyId]           = useState("");
  const [secret, setSecret]         = useState("");
  const [region, setRegion]         = useState("us-east-1");
  const [loading, setLoading]       = useState(false);
  const [report, setReport]         = useState<DriftReport | null>(null);
  const [error, setError]           = useState<string | null>(null);
  const [activeFilter, setFilter]   = useState<string>("all");

  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  async function runScan() {
    if (!keyId || !secret) {
      setError("Both AWS Access Key ID and Secret Access Key are required.");
      return;
    }

    setLoading(true);
    setError(null);
    setReport(null);

    try {
      const res = await fetch(`${apiBase}/drift`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          architecture,
          aws_access_key_id:     keyId,
          aws_secret_access_key: secret,
          region,
        }),
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
    report?.findings.filter(
      (f) => activeFilter === "all" || f.severity === activeFilter
    ) ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-gray-800">Architecture Drift Detection</h2>
        <p className="text-sm text-gray-500 mt-1">
          Connect your AWS account to compare what&rsquo;s deployed against the recommended architecture.
          Uses read-only API calls — no changes are made.
        </p>
      </div>

      {/* Credentials form */}
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 space-y-4">
        <p className="text-sm font-semibold text-gray-700">AWS Credentials</p>
        <p className="text-xs text-gray-500">
          Create a read-only IAM user with <code className="bg-gray-100 px-1 rounded">ReadOnlyAccess</code> policy.
          Credentials are never stored or logged.
        </p>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Access Key ID</label>
            <input
              type="text"
              placeholder="AKIAIOSFODNN7EXAMPLE"
              value={keyId}
              onChange={(e) => setKeyId(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Secret Access Key</label>
            <input
              type="password"
              placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div className="flex items-end gap-3">
          <div className="flex-1">
            <label className="block text-xs font-medium text-gray-600 mb-1">Region</label>
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {[
                "us-east-1", "us-east-2", "us-west-1", "us-west-2",
                "eu-west-1", "eu-west-2", "eu-central-1",
                "ap-south-1", "ap-southeast-1", "ap-southeast-2", "ap-northeast-1",
              ].map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
          <button
            onClick={runScan}
            disabled={loading}
            className="px-5 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Scanning…" : "Run Drift Scan"}
          </button>
        </div>
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
          <p className="text-sm">Scanning AWS account… this takes ~5–10 seconds</p>
        </div>
      )}

      {/* Report */}
      {report && !loading && (
        <div className="space-y-6">
          {/* Score */}
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <ScoreGauge score={report.score} />
            {report.elapsed_seconds && (
              <p className="text-xs text-gray-400 mt-3">Scan completed in {report.elapsed_seconds}s</p>
            )}
          </div>

          {/* Snapshot */}
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <SnapshotPanel snapshot={report.snapshot} />
          </div>

          {/* Findings */}
          {report.findings.length > 0 ? (
            <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <p className="font-semibold text-gray-800">
                  {report.findings.length} Drift Finding{report.findings.length !== 1 ? "s" : ""}
                </p>
                {/* Filter pills */}
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
                      {s === "all" ? "All" : SEVERITY_ICON[s] + " " + s}
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
