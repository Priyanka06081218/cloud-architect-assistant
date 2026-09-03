"use client";

// DebateTab.tsx
// Renders the multi-agent debate result:
//   • Three specialist agent cards (Cost / Reliability / Security)
//   • Moderator's final architecture
//   • Per-topic debate summary table
//   • Influence score bar

interface AgentProposal {
  agent: string;
  proposed_services?: {
    edge?: string[];
    networking?: string[];
    compute?: string[];
    database?: string[];
    messaging?: string[];
    monitoring?: string[];
  };
  argument?: string;
  estimated_monthly_usd?: number;
  estimated_sla_percent?: number;
  compliance_level?: string;
  key_decisions?: Array<{
    decision: string;
    chose: string;
    saves_usd_monthly?: number;
    uptime_impact?: string;
    risk_mitigated?: string;
    trade_off: string;
  }>;
  error?: string;
}

interface DebateSummaryItem {
  topic: string;
  cost_argued: string;
  reliability_argued: string;
  security_argued: string;
  winner: "cost" | "reliability" | "security" | "compromise";
  final_decision: string;
  rationale: string;
}

interface DebateResult {
  query: string;
  proposals: {
    cost: AgentProposal;
    reliability: AgentProposal;
    security: AgentProposal;
  };
  synthesis: {
    final_architecture: {
      layers: {
        edge?: string[];
        networking?: string[];
        compute?: string[];
        database?: string[];
        messaging?: string[];
        monitoring?: string[];
      };
      reasoning: string;
    };
    debate_summary: DebateSummaryItem[];
    scores: {
      cost_influence_pct: number;
      reliability_influence_pct: number;
      security_influence_pct: number;
    };
  };
  cached?: boolean;
  elapsed_seconds?: number;
}

//  Helpers 

const AGENT_META = {
  cost: {
    label:   "Cost Agent",
    icon:    "$",
    color:   "green",
    bg:      "bg-green-50",
    border:  "border-green-200",
    badge:   "bg-green-100 text-green-700",
    heading: "text-green-800",
  },
  reliability: {
    label:   "Reliability Agent",
    icon:    "R",
    color:   "blue",
    bg:      "bg-blue-50",
    border:  "border-blue-200",
    badge:   "bg-blue-100 text-blue-700",
    heading: "text-blue-800",
  },
  security: {
    label:   "Security Agent",
    icon:    "S",
    color:   "purple",
    bg:      "bg-purple-50",
    border:  "border-purple-200",
    badge:   "bg-purple-100 text-purple-700",
    heading: "text-purple-800",
  },
} as const;

const WINNER_STYLES: Record<string, string> = {
  cost:        "bg-green-100 text-green-700",
  reliability: "bg-blue-100 text-blue-700",
  security:    "bg-purple-100 text-purple-700",
  compromise:  "bg-orange-100 text-orange-700",
};

const LAYER_COLORS: Record<string, string> = {
  edge:        "bg-purple-100 text-purple-800",
  networking:  "bg-blue-100 text-blue-800",
  compute:     "bg-green-100 text-green-800",
  database:    "bg-yellow-100 text-yellow-800",
  messaging:   "bg-pink-100 text-pink-800",
  monitoring:  "bg-gray-100 text-gray-700",
};

function ServiceChips({ services }: { services?: string[] }) {
  if (!services?.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {services.map((s) => (
        <span key={s} className="text-xs bg-white border border-gray-200 rounded px-1.5 py-0.5 text-gray-600">
          {s}
        </span>
      ))}
    </div>
  );
}

//  Agent card 

function AgentCard({ proposal, agentKey }: { proposal: AgentProposal; agentKey: keyof typeof AGENT_META }) {
  const meta = AGENT_META[agentKey];

  return (
    <div className={`rounded-xl border ${meta.border} ${meta.bg} p-5`}>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xl">{meta.icon}</span>
        <h3 className={`font-semibold ${meta.heading}`}>{meta.label}</h3>
        {agentKey === "cost" && proposal.estimated_monthly_usd != null && (
          <span className={`ml-auto text-xs font-medium px-2 py-0.5 rounded-full ${meta.badge}`}>
            ~${proposal.estimated_monthly_usd.toLocaleString()}/mo
          </span>
        )}
        {agentKey === "reliability" && proposal.estimated_sla_percent != null && (
          <span className={`ml-auto text-xs font-medium px-2 py-0.5 rounded-full ${meta.badge}`}>
            {proposal.estimated_sla_percent}% SLA
          </span>
        )}
        {agentKey === "security" && proposal.compliance_level && (
          <span className={`ml-auto text-xs font-medium px-2 py-0.5 rounded-full ${meta.badge}`}>
            {proposal.compliance_level}
          </span>
        )}
      </div>

      {proposal.error ? (
        <p className="text-sm text-red-600">{proposal.error}</p>
      ) : (
        <>
          {/* Argument */}
          {proposal.argument && (
            <p className="text-sm text-gray-700 leading-relaxed mb-4">{proposal.argument}</p>
          )}

          {/* Services by layer */}
          {proposal.proposed_services && (
            <div className="space-y-1.5 mb-4">
              {(Object.entries(proposal.proposed_services) as [string, string[]][])
                .filter(([, svcs]) => svcs?.length)
                .map(([layer, svcs]) => (
                  <div key={layer} className="flex items-start gap-2">
                    <span className={`text-xs font-medium px-1.5 py-0.5 rounded uppercase tracking-wide shrink-0 ${LAYER_COLORS[layer] ?? "bg-gray-100 text-gray-600"}`}>
                      {layer}
                    </span>
                    <ServiceChips services={svcs} />
                  </div>
                ))}
            </div>
          )}

          {/* Key decisions */}
          {proposal.key_decisions?.length ? (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Key Decisions</p>
              {proposal.key_decisions.map((d, i) => (
                <div key={i} className="bg-white rounded-lg border border-gray-100 p-3 text-sm">
                  <div className="flex items-start justify-between gap-2 mb-1">
                    <span className="font-medium text-gray-800">{d.decision}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${meta.badge}`}>{d.chose}</span>
                  </div>
                  {d.saves_usd_monthly != null && d.saves_usd_monthly > 0 && (
                    <p className="text-xs text-green-600 mb-1">Saves ~${d.saves_usd_monthly}/mo</p>
                  )}
                  {d.uptime_impact && (
                    <p className="text-xs text-blue-600 mb-1">{d.uptime_impact}</p>
                  )}
                  {d.risk_mitigated && (
                    <p className="text-xs text-purple-600 mb-1">Mitigates: {d.risk_mitigated}</p>
                  )}
                  <p className="text-xs text-gray-500">Trade-off: {d.trade_off}</p>
                </div>
              ))}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

//  Influence bar 

function InfluenceBar({ scores }: { scores: DebateResult["synthesis"]["scores"] }) {
  const total = scores.cost_influence_pct + scores.reliability_influence_pct + scores.security_influence_pct || 100;
  const cost = Math.round((scores.cost_influence_pct / total) * 100);
  const rel  = Math.round((scores.reliability_influence_pct / total) * 100);
  const sec  = Math.round((scores.security_influence_pct / total) * 100);

  return (
    <div>
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Agent Influence</p>
      <div className="flex rounded-full overflow-hidden h-4 mb-1">
        <div className="bg-green-400 transition-all" style={{ width: `${cost}%` }} title={`Cost ${cost}%`} />
        <div className="bg-blue-400 transition-all"  style={{ width: `${rel}%` }}  title={`Reliability ${rel}%`} />
        <div className="bg-purple-400 transition-all" style={{ width: `${sec}%` }} title={`Security ${sec}%`} />
      </div>
      <div className="flex gap-4 text-xs text-gray-600">
        <span><span className="inline-block w-2 h-2 rounded-full bg-green-400 mr-1" />Cost {cost}%</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-blue-400 mr-1" />Reliability {rel}%</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-purple-400 mr-1" />Security {sec}%</span>
      </div>
    </div>
  );
}

//  Main component 

export default function DebateTab({ debate }: { debate: DebateResult }) {
  const { proposals, synthesis } = debate;

  return (
    <div className="space-y-8">

      {/* 3 Agent proposals */}
      <section>
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">
          Specialist Agent Proposals
        </h2>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <AgentCard proposal={proposals.cost}        agentKey="cost" />
          <AgentCard proposal={proposals.reliability} agentKey="reliability" />
          <AgentCard proposal={proposals.security}    agentKey="security" />
        </div>
      </section>

      {/* Moderator synthesis */}
      <section>
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">
          Moderator Synthesis
        </h2>
        <div className="rounded-xl border border-orange-200 bg-orange-50 p-5 space-y-4">
          {/* Final architecture layers */}
          {synthesis.final_architecture?.layers && (
            <div className="space-y-2">
              {(Object.entries(synthesis.final_architecture.layers) as [string, string[]][])
                .filter(([, svcs]) => svcs?.length)
                .map(([layer, svcs]) => (
                  <div key={layer} className="flex items-start gap-2">
                    <span className={`text-xs font-medium px-1.5 py-0.5 rounded uppercase tracking-wide shrink-0 ${LAYER_COLORS[layer] ?? "bg-gray-100 text-gray-600"}`}>
                      {layer}
                    </span>
                    <div className="flex flex-wrap gap-1 mt-0.5">
                      {svcs.map((s) => (
                        <span key={s} className="text-xs bg-white border border-orange-200 rounded px-1.5 py-0.5 text-gray-700">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
            </div>
          )}

          {/* Reasoning */}
          {synthesis.final_architecture?.reasoning && (
            <p className="text-sm text-gray-700 leading-relaxed">
              {synthesis.final_architecture.reasoning}
            </p>
          )}

          {/* Influence bar */}
          {synthesis.scores && <InfluenceBar scores={synthesis.scores} />}
        </div>
      </section>

      {/* Debate summary table */}
      {synthesis.debate_summary?.length ? (
        <section>
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">
            Decision-by-Decision Debate
          </h2>
          <div className="space-y-3">
            {synthesis.debate_summary.map((item, i) => (
              <div key={i} className="rounded-xl border border-gray-200 bg-white overflow-hidden">
                {/* Header row */}
                <div className="flex items-center justify-between gap-4 px-4 py-3 bg-gray-50 border-b border-gray-100">
                  <span className="font-medium text-gray-800 text-sm">{item.topic}</span>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${WINNER_STYLES[item.winner] ?? "bg-gray-100 text-gray-600"}`}>
                    {item.winner === "compromise" ? "Compromise" : `${item.winner.charAt(0).toUpperCase() + item.winner.slice(1)} won`}
                  </span>
                </div>

                {/* Argument columns */}
                <div className="grid grid-cols-3 divide-x divide-gray-100 text-xs text-gray-600">
                  <div className="p-3">
                    <p className="font-semibold text-green-700 mb-1"> Cost argued</p>
                    <p>{item.cost_argued}</p>
                  </div>
                  <div className="p-3">
                    <p className="font-semibold text-blue-700 mb-1"> Reliability argued</p>
                    <p>{item.reliability_argued}</p>
                  </div>
                  <div className="p-3">
                    <p className="font-semibold text-purple-700 mb-1"> Security argued</p>
                    <p>{item.security_argued}</p>
                  </div>
                </div>

                {/* Final decision */}
                <div className="px-4 py-3 border-t border-gray-100">
                  <p className="text-xs text-gray-500 mb-0.5">
                    <span className="font-semibold text-gray-700">Decision: </span>
                    {item.final_decision}
                  </p>
                  <p className="text-xs text-gray-500">
                    <span className="font-semibold text-gray-700">Rationale: </span>
                    {item.rationale}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
