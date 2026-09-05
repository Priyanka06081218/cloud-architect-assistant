"use client";

interface PerformanceData {
  p50_ms: number;
  p95_ms: number;
  max_rps: number;
  availability: number;
  availability_pct: string;
  nines: string;
  notes: string[];
}

export default function PerformanceTab({ performance }: { performance: PerformanceData }) {
  const availColor =
    performance.availability >= 0.9999  ? "text-green-600"  :
    performance.availability >= 0.999   ? "text-yellow-600" :
                                          "text-red-600";

  const latencyColor = (ms: number) =>
    ms < 100 ? "text-green-600" :
    ms < 300 ? "text-yellow-600" :
               "text-red-600";

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Metric
          label="p50 Latency"
          value={`${performance.p50_ms} ms`}
          sub="median response time"
          valueClass={latencyColor(performance.p50_ms)}
        />
        <Metric
          label="p95 Latency"
          value={`${performance.p95_ms} ms`}
          sub="95th-percentile response time"
          valueClass={latencyColor(performance.p95_ms)}
        />
        <Metric
          label="Peak Throughput"
          value={performance.max_rps.toLocaleString()}
          sub="estimated max requests/sec"
          valueClass="text-blue-600"
        />
      </div>

      <div className="rounded-lg border border-gray-200 p-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-gray-700">Availability (SLA-based)</span>
          <span className={`text-lg font-semibold ${availColor}`}>{performance.availability_pct}</span>
        </div>
        <div className="mt-1">
          <div className="h-2 w-full rounded bg-gray-100 overflow-hidden">
            <div
              className={`h-2 rounded ${performance.availability >= 0.9999 ? "bg-green-500" : performance.availability >= 0.999 ? "bg-yellow-400" : "bg-red-500"}`}
              style={{ width: `${performance.availability * 100}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-gray-500">{performance.nines}</p>
        </div>
      </div>

      {performance.notes.length > 0 && (
        <div className="rounded-lg border border-blue-100 bg-blue-50 p-4">
          <p className="mb-2 text-sm font-medium text-blue-800">Modeling notes</p>
          <ul className="space-y-1">
            {performance.notes.map((note, i) => (
              <li key={i} className="text-sm text-blue-700">• {note}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-xs text-gray-400">
        Estimates based on documented service SLAs and typical benchmark ranges.
        Treat as order-of-magnitude guidance for architecture comparison, not production SLOs.
      </p>
    </div>
  );
}

function Metric({ label, value, sub, valueClass }: {
  label: string; value: string; sub: string; valueClass: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${valueClass}`}>{value}</p>
      <p className="text-xs text-gray-400">{sub}</p>
    </div>
  );
}
