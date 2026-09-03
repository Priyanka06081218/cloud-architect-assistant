"use client";

import { useState } from "react";

const EXAMPLES = [
  "Design an AWS architecture for an e-commerce app expecting 100k concurrent users during Black Friday.",
  "Build a serverless REST API on Azure for a mobile app with 50k daily active users. Keep costs minimal.",
  "Design a HIPAA-compliant data pipeline on GCP for processing patient health records in real time.",
];

interface Props {
  onSubmit: (query: string) => void;
  loading: boolean;
}

export default function QueryForm({ onSubmit, loading }: Props) {
  const [query, setQuery] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (query.trim().length >= 10) onSubmit(query.trim());
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
      <label className="block text-sm font-medium text-gray-700 mb-2">
        Describe your cloud architecture scenario — mention AWS, Azure, or GCP
      </label>
      <textarea
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="e.g. Design an Azure architecture for a video streaming platform with 1M daily active users, or describe your scenario on AWS or GCP..."
        rows={4}
        className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm text-gray-900
                   placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-orange-400
                   focus:border-transparent resize-none"
        disabled={loading}
      />

      <div className="mt-3 flex items-center justify-between">
        {/* Example queries */}
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setQuery(ex)}
              className="text-xs text-orange-600 bg-orange-50 hover:bg-orange-100 border
                         border-orange-200 rounded-full px-3 py-1 transition-colors"
              disabled={loading}
            >
              Example {i + 1}
            </button>
          ))}
        </div>

        <button
          type="submit"
          disabled={loading || query.trim().length < 10}
          className="flex items-center gap-2 bg-orange-500 hover:bg-orange-600 disabled:bg-gray-300
                     disabled:cursor-not-allowed text-white font-medium text-sm rounded-lg
                     px-5 py-2.5 transition-colors ml-4 shrink-0"
        >
          {loading ? (
            <>
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Analyzing…
            </>
          ) : (
            "Analyze →"
          )}
        </button>
      </div>
    </form>
  );
}
