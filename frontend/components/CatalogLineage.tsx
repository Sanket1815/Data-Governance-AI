"use client";

import { ArrowRight, GitBranch } from "lucide-react";
import { useEffect, useState } from "react";
import { getLineage } from "@/lib/catalogApi";
import { CatalogApiError, LineageResponse } from "@/lib/catalogTypes";

function layerNodes(lineage: LineageResponse): string[][] {
  const nodeNames = lineage.nodes.map((n) => n.table);
  const inbound = new Map<string, Set<string>>(nodeNames.map((n) => [n, new Set()]));
  for (const edge of lineage.edges) {
    inbound.get(edge.target)?.add(edge.source);
  }

  const placed = new Set<string>();
  const layers: string[][] = [];
  let remaining = new Set(nodeNames);

  while (remaining.size > 0) {
    const layer = [...remaining].filter((n) => [...(inbound.get(n) ?? [])].every((dep) => placed.has(dep)));
    if (layer.length === 0) {
      layers.push([...remaining]);
      break;
    }
    layers.push(layer);
    layer.forEach((n) => {
      placed.add(n);
      remaining.delete(n);
    });
  }
  return layers;
}

export default function CatalogLineage() {
  const [lineage, setLineage] = useState<LineageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getLineage()
      .then(setLineage)
      .catch((err) => setError(err instanceof CatalogApiError ? err.message : "Failed to load lineage."));
  }, []);

  return (
    <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
      <div className="mb-1 flex items-center gap-2">
        <GitBranch className="h-4 w-4 text-gray-400" />
        <h3 className="text-sm font-medium text-gray-200">Pipeline Lineage</h3>
      </div>
      <p className="mb-3 text-xs text-gray-500">
        Derived from the FWA feature/anomaly pipeline itself, not auto-discovered.
      </p>

      {error && <p className="text-xs text-red-400">{error}</p>}

      {lineage && (
        <div className="scrollbar-thin overflow-x-auto">
          <div className="flex min-w-max items-start gap-6 py-2">
            {layerNodes(lineage).map((layer, layerIndex, allLayers) => (
              <div key={layerIndex} className="flex items-center gap-6">
                <div className="flex flex-col gap-2">
                  {layer.map((table) => (
                    <div
                      key={table}
                      className="rounded-lg border border-surface-border bg-surface px-3 py-2 text-xs font-mono text-gray-200"
                    >
                      {table}
                    </div>
                  ))}
                </div>
                {layerIndex < allLayers.length - 1 && <ArrowRight className="h-4 w-4 shrink-0 text-gray-600" />}
              </div>
            ))}
          </div>
          <ul className="mt-3 space-y-1 border-t border-surface-border pt-3 text-xs text-gray-500">
            {lineage.edges.map((edge) => (
              <li key={`${edge.source}-${edge.target}`}>
                <span className="font-mono text-gray-400">{edge.source}</span> → <span className="font-mono text-gray-400">{edge.target}</span>: {edge.description}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
