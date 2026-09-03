"use client";

import { useState } from "react";
import QueryForm from "./components/QueryForm";
import ResultTabs from "./components/ResultTabs";

// Shape of the API response
export interface AnalyzeResponse {
  scenario_summary: string;
  cloud_provider?: string;   // "AWS" | "Azure" | "GCP"
  architecture: {
    layers: {
      edge?: string[];
      networking?: string[];
      compute?: string[];
      database?: string[];
      messaging?: string[];
      monitoring?: string[];
      security?: string[];
    };
    reasoning: string;
  };
  trade_offs: Array<{
    decision: string;
    chose: string;
    reason: string;
    when_to_switch: string;
  }>;
  cost: {
    monthly_breakdown: Array<{
      service: string;
      monthly_usd: number;
      unit: string;
    }>;
    total_monthly_usd: number;
    spike_estimate_usd: number;
    cloud_provider?: string;
    optimization: string;
  };
  constraint_violations?: Array<{
    constraint_type: string;
    severity: string;
    description: string;
    suggestion: string;
  }>;
  terraform: string;
  diagram: string;
  cached: boolean;
  elapsed_seconds?: number;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(query: string) {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch(`${API_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? `Server error ${res.status}`);
      }

      const data: AnalyzeResponse = await res.json();
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 font-sans">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-3">
          <div className="w-8 h-8 bg-orange-500 rounded-lg flex items-center justify-center">
            <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" />
            </svg>
          </div>
          <div>
            <h1 className="text-lg font-semibold text-gray-900">Cloud Architecture Assistant</h1>
            <p className="text-xs text-gray-500">AI-powered multi-cloud architecture recommendations — AWS, Azure, GCP</p>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">
        {/* Query form */}
        <QueryForm onSubmit={handleSubmit} loading={loading} />

        {/* Error */}
        {error && (
          <div className="mt-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            <strong>Error:</strong> {error}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="mt-8 space-y-4 animate-pulse">
            <div className="h-4 bg-gray-200 rounded w-1/3" />
            <div className="h-4 bg-gray-200 rounded w-2/3" />
            <div className="h-4 bg-gray-200 rounded w-1/2" />
            <div className="h-32 bg-gray-200 rounded mt-4" />
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <div className="mt-8">
            {/* Summary banner */}
            <div className="bg-orange-50 border border-orange-200 rounded-xl p-5 mb-6">
              <div className="flex items-center gap-2 mb-1">
                <p className="text-sm font-medium text-orange-700">Scenario Summary</p>
                {result.cloud_provider && (
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full
                    ${result.cloud_provider === "AWS"   ? "bg-yellow-100 text-yellow-700" :
                      result.cloud_provider === "Azure" ? "bg-blue-100 text-blue-700" :
                      result.cloud_provider === "GCP"   ? "bg-green-100 text-green-700" :
                                                          "bg-gray-100 text-gray-600"}`}>
                    {result.cloud_provider}
                  </span>
                )}
              </div>
              <p className="text-gray-800">{result.scenario_summary}</p>
              <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
                {result.cached && (
                  <span className="bg-orange-100 text-orange-600 px-2 py-0.5 rounded-full">cached</span>
                )}
                {result.elapsed_seconds && (
                  <span>Generated in {result.elapsed_seconds}s</span>
                )}
                <span>Est. ${result.cost.total_monthly_usd}/mo</span>
                {result.constraint_violations && result.constraint_violations.length > 0 && (
                  <span className="bg-red-100 text-red-600 px-2 py-0.5 rounded-full">
                    {result.constraint_violations.length} constraint {result.constraint_violations.length === 1 ? "violation" : "violations"}
                  </span>
                )}
              </div>
            </div>

            <ResultTabs result={result} />
          </div>
        )}
      </main>
    </div>
  );
}
