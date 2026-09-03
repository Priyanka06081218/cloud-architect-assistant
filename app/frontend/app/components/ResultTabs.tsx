"use client";

import { useState } from "react";
import type { AnalyzeResponse } from "../page";
import ArchitectureTab from "./tabs/ArchitectureTab";
import TradeOffsTab from "./tabs/TradeOffsTab";
import CostTab from "./tabs/CostTab";
import TerraformTab from "./tabs/TerraformTab";
import DiagramTab from "./tabs/DiagramTab";
import DebateTab from "./tabs/DebateTab";
import DriftTab from "./tabs/DriftTab";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TABS = [
  { id: "architecture", label: "Architecture" },
  { id: "tradeoffs",    label: "Trade-offs" },
  { id: "cost",         label: "Cost" },
  { id: "terraform",    label: "Terraform" },
  { id: "diagram",      label: "Diagram" },
  { id: "debate",       label: "Debate" },
  { id: "drift",        label: "Drift" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function ResultTabs({ result }: { result: AnalyzeResponse }) {
  const [active, setActive]         = useState<TabId>("architecture");
  const [debate, setDebate]         = useState<object | null>(null);
  const [debateLoading, setDebateLoading] = useState(false);
  const [debateError, setDebateError]     = useState<string | null>(null);

  async function fetchDebate() {
    if (debate) return; // already loaded
    setDebateLoading(true);
    setDebateError(null);
    try {
      const res = await fetch(`${API_URL}/analyze/debate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: result.scenario_summary }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error((data as { detail?: string }).detail ?? `Server error ${res.status}`);
      }
      setDebate(await res.json());
    } catch (err) {
      setDebateError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setDebateLoading(false);
    }
  }

  function handleTabClick(id: TabId) {
    setActive(id);
    if (id === "debate") fetchDebate();
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b border-gray-200 overflow-x-auto">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => handleTabClick(tab.id)}
            className={`px-5 py-3 text-sm font-medium whitespace-nowrap transition-colors
              ${active === tab.id
                ? "border-b-2 border-orange-500 text-orange-600 bg-orange-50"
                : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
              }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="p-6">
        {active === "architecture" && <ArchitectureTab architecture={result.architecture} />}
        {active === "tradeoffs"    && <TradeOffsTab tradeOffs={result.trade_offs} />}
        {active === "cost"         && <CostTab cost={result.cost} />}
        {active === "terraform"    && <TerraformTab code={result.terraform} />}
        {active === "diagram"      && <DiagramTab diagram={result.diagram} />}
        {active === "drift" && (
          <DriftTab architecture={result.architecture} />
        )}
        {active === "debate" && (
          debateLoading ? (
            <div className="flex flex-col items-center justify-center py-16 gap-4">
              <svg className="animate-spin w-8 h-8 text-orange-500" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              <p className="text-sm text-gray-500">Running Cost, Reliability &amp; Security agents in parallel…</p>
            </div>
          ) : debateError ? (
            <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
              <strong>Error:</strong> {debateError}
            </div>
          ) : debate ? (
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            <DebateTab debate={debate as any} />
          ) : null
        )}
      </div>
    </div>
  );
}
