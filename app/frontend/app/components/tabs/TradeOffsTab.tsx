import type { AnalyzeResponse } from "../../page";

type TradeOff = AnalyzeResponse["trade_offs"][number];

export default function TradeOffsTab({ tradeOffs }: { tradeOffs: TradeOff[] }) {
  if (!tradeOffs || tradeOffs.length === 0) {
    return <p className="text-sm text-gray-500">No trade-offs available.</p>;
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-4">
        Architecture Decisions
      </h3>
      {tradeOffs.map((t, i) => (
        <div key={i} className="border border-gray-200 rounded-lg p-5 space-y-3">
          {/* Decision header */}
          <div className="flex items-start justify-between gap-4">
            <span className="text-sm font-semibold text-gray-800">{t.decision}</span>
            <span className="text-xs font-medium bg-green-100 text-green-700 border border-green-200
                             px-2.5 py-1 rounded-full whitespace-nowrap">
              {t.chose}
            </span>
          </div>

          {/* Reason */}
          <div>
            <p className="text-xs font-medium text-gray-500 mb-1">Why this choice</p>
            <p className="text-sm text-gray-700">{t.reason}</p>
          </div>

          {/* When to switch */}
          <div className="bg-amber-50 border border-amber-200 rounded p-3">
            <p className="text-xs font-medium text-amber-700 mb-1">When to reconsider</p>
            <p className="text-sm text-amber-800">{t.when_to_switch}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
