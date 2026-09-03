"use client";

import { useEffect, useRef, useState } from "react";

export default function DiagramTab({ diagram }: { diagram: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!diagram || !containerRef.current) return;

    let cancelled = false;

    async function render() {
      try {
        const mermaid = (await import("mermaid")).default;

        mermaid.initialize({
          startOnLoad: false,
          theme: "base",
          themeVariables: {
            primaryColor: "#fff7ed",
            primaryBorderColor: "#f97316",
            primaryTextColor: "#1f2937",
            lineColor: "#6b7280",
            secondaryColor: "#f3f4f6",
            tertiaryColor: "#fef3c7",
          },
        });

        const id = `mermaid-${Date.now()}`;
        const { svg } = await mermaid.render(id, diagram);

        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
          // Make the SVG responsive
          const svgEl = containerRef.current.querySelector("svg");
          if (svgEl) {
            svgEl.removeAttribute("height");
            svgEl.setAttribute("width", "100%");
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Diagram render failed");
        }
      }
    }

    render();
    return () => { cancelled = true; };
  }, [diagram]);

  if (error) {
    return (
      <div className="space-y-3">
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          <p className="font-medium mb-1">Diagram render error</p>
          <p className="text-xs font-mono">{error}</p>
        </div>
        {/* Fallback: show raw Mermaid source */}
        <details className="text-xs">
          <summary className="cursor-pointer text-gray-500 hover:text-gray-700">Show raw Mermaid source</summary>
          <pre className="mt-2 bg-gray-50 border border-gray-200 rounded p-3 overflow-x-auto text-gray-700">
            {diagram}
          </pre>
        </details>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide">
        Architecture Diagram
      </h3>
      <div
        ref={containerRef}
        className="w-full min-h-48 bg-gray-50 border border-gray-200 rounded-xl p-4 flex items-center justify-center"
      >
        <span className="text-sm text-gray-400 animate-pulse">Rendering diagram…</span>
      </div>
      {/* Also show raw source so users can paste into mermaid.live */}
      <details className="text-xs">
        <summary className="cursor-pointer text-gray-500 hover:text-gray-700 select-none">
          Show Mermaid source (paste into mermaid.live to edit)
        </summary>
        <pre className="mt-2 bg-gray-50 border border-gray-200 rounded p-3 overflow-x-auto text-gray-700">
          {diagram}
        </pre>
      </details>
    </div>
  );
}
