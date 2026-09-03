import type { AnalyzeResponse } from "../../page";

const LAYER_COLORS: Record<string, string> = {
  edge:       "bg-purple-100 text-purple-700 border-purple-200",
  networking: "bg-blue-100 text-blue-700 border-blue-200",
  compute:    "bg-green-100 text-green-700 border-green-200",
  database:   "bg-yellow-100 text-yellow-700 border-yellow-200",
  messaging:  "bg-pink-100 text-pink-700 border-pink-200",
  monitoring: "bg-gray-100 text-gray-700 border-gray-200",
};

const LAYER_ICONS: Record<string, string> = {
  edge:       "",
  networking: "",
  compute:    "",
  database:   "",
  messaging:  "",
  monitoring: "",
};

type Architecture = AnalyzeResponse["architecture"];

export default function ArchitectureTab({ architecture }: { architecture: Architecture }) {
  const layers = architecture.layers ?? {};
  const activeLayers = Object.entries(layers).filter(([, svcs]) => svcs && svcs.length > 0);

  return (
    <div className="space-y-6">
      {/* Layer grid */}
      <div>
        <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-4">
          Service Layers
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {activeLayers.map(([layer, services]) => (
            <div key={layer} className="border border-gray-200 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                
                <span className="text-sm font-semibold text-gray-700 capitalize">{layer}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {services.map((svc) => (
                  <span
                    key={svc}
                    className={`text-xs font-medium px-2.5 py-1 rounded-full border ${LAYER_COLORS[layer] ?? "bg-gray-100 text-gray-700 border-gray-200"}`}
                  >
                    {svc}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Reasoning */}
      {architecture.reasoning && (
        <div>
          <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-3">
            Reasoning
          </h3>
          <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
            {architecture.reasoning}
          </div>
        </div>
      )}
    </div>
  );
}
