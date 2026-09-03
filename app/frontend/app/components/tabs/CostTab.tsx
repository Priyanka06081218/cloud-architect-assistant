import type { AnalyzeResponse } from "../../page";

type Cost = AnalyzeResponse["cost"];

export default function CostTab({ cost }: { cost: Cost }) {
  const { monthly_breakdown, total_monthly_usd, spike_estimate_usd, optimization } = cost;

  return (
    <div className="space-y-6">
      {/* Totals */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-5 text-center">
          <p className="text-xs font-medium text-blue-600 mb-1">Monthly Estimate</p>
          <p className="text-3xl font-bold text-blue-800">${total_monthly_usd.toFixed(2)}</p>
          <p className="text-xs text-blue-500 mt-1">us-east-1 on-demand</p>
        </div>
        <div className="bg-orange-50 border border-orange-200 rounded-xl p-5 text-center">
          <p className="text-xs font-medium text-orange-600 mb-1">Peak / Spike</p>
          <p className="text-3xl font-bold text-orange-800">${spike_estimate_usd.toFixed(2)}</p>
          <p className="text-xs text-orange-500 mt-1">~35% above normal</p>
        </div>
      </div>

      {/* Line items */}
      <div>
        <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-3">
          Monthly Breakdown
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
              {monthly_breakdown.map((item, i) => {
                const pct = total_monthly_usd > 0
                  ? Math.round((item.monthly_usd / total_monthly_usd) * 100)
                  : 0;
                return (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-800">{item.service}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{item.unit}</td>
                    <td className="px-4 py-3 text-right font-mono text-gray-800">
                      ${item.monthly_usd.toFixed(2)}
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
                  ${total_monthly_usd.toFixed(2)}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* Optimization tip */}
      {optimization && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <p className="text-xs font-semibold text-green-700 mb-1">Cost Optimization Tip</p>
          <p className="text-sm text-green-800">{optimization}</p>
        </div>
      )}
    </div>
  );
}
