"use client";

import { useState } from "react";
import type { AnalyzeResponse } from "../../page";

type Cost = AnalyzeResponse["cost"];
type Scenario = Cost["scenarios"][number];

// Scale presets: label → approximate daily-user multiplier relative to balanced
const SCALE_PRESETS = [
  { label: "Startup",    description: "< 5k daily users",      factor: 0.25 },
  { label: "Growth",     description: "5k – 50k daily users",  factor: 1.0  },
  { label: "Scale",      description: "50k – 500k daily users",factor: 2.5  },
  { label: "Enterprise", description: "500k+ daily users",     factor: 8.0  },
] as const;

function fmt(n: number) {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function RangeBar({ min, current, max }: { min: number; current: number; max: number }) {
  const pct = max > min ? Math.round(((current - min) / (max - min)) * 100) : 50;
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs text-gray-500 font-medium">
        <span>Cost-Optimized<br /><span className="text-green-700 font-semibold">{fmt(min)}/mo</span></span>
        <span className="text-center">Balanced<br /><span className="text-blue-700 font-semibold">{fmt(current)}/mo</span></span>
        <span className="text-right">High Availability<br /><span className="text-purple-700 font-semibold">{fmt(max)}/mo</span></span>
      </div>
      <div className="relative h-2 bg-gray-200 rounded-full">
        <div
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-green-400 via-blue-400 to-purple-500 rounded-full"
          style={{ width: "100%" }}
        />
        {/* Marker for current scenario */}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-4 h-4 bg-white border-2 border-blue-500 rounded-full shadow"
          style={{ left: `calc(${pct}% - 8px)` }}
        />
      </div>
    </div>
  );
}

export default function CostTab({ cost }: { cost: Cost }) {
  const {
    scenarios,
    min_monthly_usd,
    max_monthly_usd,
    total_monthly_usd,
    optimization,
  } = cost;

  // Fallback: if backend doesn't return scenarios (old cache hit), synthesise one
  const safeScenarios: Scenario[] = scenarios?.length
    ? scenarios
    : [
        {
          id: "balanced",
          label: "Balanced",
          description: "Production-ready with sensible defaults.",
          recommended: true,
          total_monthly_usd,
          spike_estimate_usd: cost.spike_estimate_usd,
          monthly_breakdown: cost.monthly_breakdown,
        },
      ];

  const defaultScenario = safeScenarios.find((s) => s.recommended) ?? safeScenarios[0];
  const [activeScenario, setActiveScenario] = useState<Scenario>(defaultScenario);
  const [scaleFactor, setScaleFactor] = useState(1.0);
  const [activePreset, setActivePreset] = useState<string | null>("Growth");

  const adjustedTotal = Math.round(activeScenario.total_monthly_usd * scaleFactor);
  const adjustedSpike = Math.round(activeScenario.spike_estimate_usd * scaleFactor);

  function applyPreset(preset: (typeof SCALE_PRESETS)[number]) {
    setScaleFactor(preset.factor);
    setActivePreset(preset.label);
  }

  const scenarioColors: Record<string, string> = {
    cost_optimized:   "border-green-400 bg-green-50",
    balanced:         "border-blue-500 bg-blue-50",
    high_availability:"border-purple-400 bg-purple-50",
  };
  const scenarioRing: Record<string, string> = {
    cost_optimized:   "ring-green-400",
    balanced:         "ring-blue-500",
    high_availability:"ring-purple-400",
  };
  const scenarioText: Record<string, string> = {
    cost_optimized:   "text-green-700",
    balanced:         "text-blue-700",
    high_availability:"text-purple-700",
  };

  return (
    <div className="space-y-6">

      {/* ── Scenario selector ─────────────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-3">
          Choose a scenario
        </h3>
        <div className="grid grid-cols-3 gap-3">
          {safeScenarios.map((s) => {
            const isActive = activeScenario.id === s.id;
            return (
              <button
                key={s.id}
                onClick={() => { setActiveScenario(s); setScaleFactor(1.0); setActivePreset("Growth"); }}
                className={`
                  relative text-left rounded-xl border-2 p-4 transition-all
                  ${isActive
                    ? `${scenarioColors[s.id] ?? "border-gray-300 bg-gray-50"} ring-2 ${scenarioRing[s.id] ?? "ring-gray-400"}`
                    : "border-gray-200 bg-white hover:border-gray-300"
                  }
                `}
              >
                {s.recommended && (
                  <span className="absolute -top-2.5 left-3 text-xs font-semibold bg-blue-500 text-white px-2 py-0.5 rounded-full">
                    ⭐ Recommended
                  </span>
                )}
                <p className={`text-xs font-semibold uppercase tracking-wide mb-1 ${isActive ? scenarioText[s.id] : "text-gray-500"}`}>
                  {s.label}
                </p>
                <p className={`text-2xl font-bold ${isActive ? scenarioText[s.id] : "text-gray-700"}`}>
                  {fmt(s.total_monthly_usd)}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">/month</p>
                <p className="text-xs text-gray-500 mt-2 leading-snug">{s.description}</p>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Cost range bar ────────────────────────────────────────────────── */}
      {safeScenarios.length > 1 && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Cost range for this architecture
          </p>
          <RangeBar
            min={min_monthly_usd ?? safeScenarios[0].total_monthly_usd}
            current={activeScenario.total_monthly_usd}
            max={max_monthly_usd ?? safeScenarios[safeScenarios.length - 1].total_monthly_usd}
          />
        </div>
      )}

      {/* ── Scale Explorer ────────────────────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-4">
        <p className="text-sm font-semibold text-gray-700">
          Scale Explorer
          <span className="ml-2 text-xs font-normal text-gray-400">— adjust cost by workload size</span>
        </p>

        {/* Preset buttons */}
        <div className="flex gap-2 flex-wrap">
          {SCALE_PRESETS.map((p) => (
            <button
              key={p.label}
              onClick={() => applyPreset(p)}
              className={`
                text-xs px-3 py-1.5 rounded-full border font-medium transition-colors
                ${activePreset === p.label
                  ? "bg-orange-500 border-orange-500 text-white"
                  : "border-gray-300 text-gray-600 hover:border-orange-400 hover:text-orange-600"
                }
              `}
            >
              {p.label}
              <span className="ml-1 opacity-60">{p.description}</span>
            </button>
          ))}
        </div>

        {/* Continuous slider */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-500">
            <span>0.1×</span>
            <span className="font-medium text-gray-700">Scale factor: <strong>{scaleFactor.toFixed(1)}×</strong></span>
            <span>10×</span>
          </div>
          <input
            type="range"
            min={0.1}
            max={10}
            step={0.1}
            value={scaleFactor}
            onChange={(e) => { setScaleFactor(parseFloat(e.target.value)); setActivePreset(null); }}
            className="w-full accent-orange-500"
          />
        </div>

        {/* Adjusted estimate */}
        <div className="flex items-center gap-6 bg-orange-50 border border-orange-200 rounded-lg p-3">
          <div>
            <p className="text-xs text-orange-600 font-medium">Adjusted Monthly</p>
            <p className="text-2xl font-bold text-orange-800">{fmt(adjustedTotal)}</p>
          </div>
          <div>
            <p className="text-xs text-orange-500 font-medium">Peak / Spike</p>
            <p className="text-lg font-semibold text-orange-700">{fmt(adjustedSpike)}</p>
            <p className="text-xs text-orange-400">~35% above normal</p>
          </div>
          {scaleFactor !== 1 && (
            <div className="ml-auto text-xs text-gray-400 text-right leading-snug">
              Approximate — scales<br />proportionally to base cost.
            </div>
          )}
        </div>
      </div>

      {/* ── Monthly breakdown ─────────────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-3">
          Monthly Breakdown
          <span className="ml-2 text-xs font-normal text-gray-400 normal-case">
            — {activeScenario.label} scenario
            {scaleFactor !== 1 && `, ${scaleFactor.toFixed(1)}× scale`}
          </span>
        </h3>
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-3">Service</th>
                <th className="px-4 py-3">Unit</th>
                <th className="px-4 py-3 text-right">Monthly (USD)</th>
                <th className="px-4 py-3 w-32">Share</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {activeScenario.monthly_breakdown.map((item, i) => {
                const adjustedItem = item.monthly_usd * scaleFactor;
                const pct = adjustedTotal > 0
                  ? Math.round((adjustedItem / adjustedTotal) * 100)
                  : 0;
                return (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-800">{item.service}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{item.unit}</td>
                    <td className="px-4 py-3 text-right font-mono text-gray-800">
                      ${adjustedItem.toFixed(2)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 bg-gray-200 rounded-full h-1.5 overflow-hidden">
                          <div
                            className="h-full bg-orange-400 rounded-full"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-500 w-8 text-right">{pct}%</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="bg-gray-50 font-semibold">
                <td className="px-4 py-3 text-gray-800" colSpan={2}>Total</td>
                <td className="px-4 py-3 text-right font-mono text-gray-900">
                  {fmt(adjustedTotal)}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* ── Optimization tip ──────────────────────────────────────────────── */}
      {optimization && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <p className="text-xs font-semibold text-green-700 mb-1">Cost Optimization Tip</p>
          <p className="text-sm text-green-800">{optimization}</p>
        </div>
      )}
    </div>
  );
}
