"use client";

import React, { useState, useEffect } from 'react';

interface ProviderInfo {
  name: string;
  display_name: string;
  capabilities: {
    max_context_length: number;
    supports_streaming: boolean;
    supports_function_calling: boolean;
    supports_vision: boolean;
    cost_per_1k_input_tokens: number;
    cost_per_1k_output_tokens: number;
  };
  available_models: string[];
  key_format: {
    prefix: string;
    length: string;
    example: string;
    description: string;
  };
}

interface ProviderSelectorProps {
  userApiKeys?: Array<{
    id: string;
    provider: string;
    key_name: string;
    is_active: boolean;
  }>;
}

const ProviderSelector: React.FC<ProviderSelectorProps> = ({
  userApiKeys = [],
}) => {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);

  useEffect(() => {
    fetchProviders();
  }, []);

  const fetchProviders = async () => {
    try {
      const response = await fetch('/api/byok/providers');
      if (response.ok) {
        const data = await response.json();
        const list = Array.isArray(data.providers) ? data.providers : [];
        setProviders(list);
      }
    } catch (error) {
      console.error('Failed to fetch providers:', error);
    } finally {
      setLoading(false);
    }
  };

  const hasUserKey = (providerName: string) =>
    userApiKeys.some((k) => k.provider === providerName && k.is_active);

  const formatCtx = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
    return String(n);
  };

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="animate-pulse rounded-xl border border-white/5 bg-white/[0.02] p-5">
            <div className="h-4 w-28 rounded bg-white/10" />
            <div className="mt-3 h-3 w-48 rounded bg-white/5" />
          </div>
        ))}
      </div>
    );
  }

  if (providers.length === 0) {
    return (
      <p className="text-sm text-zinc-500">No providers available.</p>
    );
  }

  return (
    <div className="space-y-3">
      {providers.map((provider) => {
        const hasKey = hasUserKey(provider.name);
        const isExpanded = expandedProvider === provider.name;
        const cap = provider.capabilities;

        return (
          <button
            key={provider.name}
            type="button"
            onClick={() => setExpandedProvider(isExpanded ? null : provider.name)}
            className={`w-full text-left rounded-xl border p-5 transition ${
              isExpanded
                ? 'border-orange-300/25 bg-orange-300/[0.04]'
                : 'border-white/5 bg-white/[0.02] hover:border-white/10 hover:bg-white/[0.04]'
            }`}
          >
            {/* Header row */}
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                  {provider.display_name}
                </h3>
                {hasKey ? (
                  <span className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-300 ring-1 ring-emerald-400/20">
                    Your Key
                  </span>
                ) : (
                  <span className="rounded-md bg-sky-500/10 px-2 py-0.5 text-[10px] font-bold text-sky-300 ring-1 ring-sky-400/20">
                    Default
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 text-xs text-zinc-500">
                <span>{provider.available_models.length} models</span>
                <span>{formatCtx(cap.max_context_length)} ctx</span>
                <span className={`transition ${isExpanded ? 'rotate-180' : ''}`}>▾</span>
              </div>
            </div>

            {/* Feature badges */}
            <div className="mt-3 flex flex-wrap gap-1.5">
              {cap.supports_streaming && (
                <span className="rounded-md bg-violet-500/10 px-2 py-0.5 text-[10px] font-semibold text-violet-300 ring-1 ring-violet-400/20">
                  Streaming
                </span>
              )}
              {cap.supports_function_calling && (
                <span className="rounded-md bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold text-blue-300 ring-1 ring-blue-400/20">
                  Function Calling
                </span>
              )}
              {cap.supports_vision && (
                <span className="rounded-md bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300 ring-1 ring-amber-400/20">
                  Vision
                </span>
              )}
            </div>

            {/* Expanded details */}
            {isExpanded && (
              <div className="mt-4 space-y-4 border-t border-white/5 pt-4" onClick={(e) => e.stopPropagation()}>
                {/* Pricing */}
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="rounded-lg border border-white/5 bg-black/25 p-3">
                    <p className="text-zinc-500">Input cost</p>
                    <p className="mt-0.5 font-semibold text-zinc-200">
                      ${cap.cost_per_1k_input_tokens.toFixed(4)}<span className="text-zinc-500 font-normal"> /1K tokens</span>
                    </p>
                  </div>
                  <div className="rounded-lg border border-white/5 bg-black/25 p-3">
                    <p className="text-zinc-500">Output cost</p>
                    <p className="mt-0.5 font-semibold text-zinc-200">
                      ${cap.cost_per_1k_output_tokens.toFixed(4)}<span className="text-zinc-500 font-normal"> /1K tokens</span>
                    </p>
                  </div>
                </div>

                {/* Models list */}
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">
                    Available Models
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {provider.available_models.slice(0, 10).map((model) => (
                      <span
                        key={model}
                        className="rounded-md border border-white/5 bg-black/25 px-2 py-1 text-[11px] font-mono text-zinc-300"
                      >
                        {model}
                      </span>
                    ))}
                    {provider.available_models.length > 10 && (
                      <span className="rounded-md px-2 py-1 text-[11px] text-zinc-500">
                        +{provider.available_models.length - 10} more
                      </span>
                    )}
                  </div>
                </div>

                {/* Key format */}
                <div className="rounded-lg border border-white/5 bg-black/25 p-3 text-xs">
                  <p className="text-zinc-500">{provider.key_format.description}</p>
                  <p className="mt-1 font-mono text-zinc-400">
                    Example: <span className="text-zinc-300">{provider.key_format.example}</span>
                  </p>
                </div>

                {/* CTA for users without a key */}
                {!hasKey && (
                  <div className="rounded-lg border border-sky-500/15 bg-sky-500/[0.06] p-3 text-xs">
                    <p className="font-semibold text-sky-300">Using Default API Key</p>
                    <p className="mt-0.5 text-sky-400/80">
                      Add your own {provider.display_name} key above to skip usage limits.
                    </p>
                  </div>
                )}
              </div>
            )}
          </button>
        );
      })}
    </div>
  );
};

export default ProviderSelector;
