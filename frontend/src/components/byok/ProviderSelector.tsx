"use client";

import React, { useState, useEffect } from 'react';
import { ChevronDown, Zap, Clock, DollarSign, CheckCircle } from 'lucide-react';

interface Model {
  id: string;
  name: string;
  context_length: number;
  features: string[];
}

interface Provider {
  id: string;
  name: string;
  models: Model[];
  max_context_length: number;
  supported_features: string[];
}

interface ProviderSelectorProps {
  selectedProvider?: string;
  selectedModel?: string;
  onProviderChange: (provider: string) => void;
  onModelChange: (model: string) => void;
  userApiKeys?: Array<{
    id: string;
    provider: string;
    key_name: string;
    is_active: boolean;
  }>;
}

const ProviderSelector: React.FC<ProviderSelectorProps> = ({
  selectedProvider,
  selectedModel,
  onProviderChange,
  onModelChange,
  userApiKeys = []
}) => {
  const [providers, setProviders] = useState<Record<string, Provider>>({});
  const [loading, setLoading] = useState(true);
  const [showProviderDropdown, setShowProviderDropdown] = useState(false);
  const [showModelDropdown, setShowModelDropdown] = useState(false);

  useEffect(() => {
    fetchProviders();
  }, []);

  const fetchProviders = async () => {
    try {
      const response = await fetch('/api/byok/providers');
      if (response.ok) {
        const data = await response.json();
        
        // Convert to provider objects with capabilities
        const providerData: Record<string, Provider> = {};
        for (const [providerName, models] of Object.entries(data.providers || {})) {
          const capResponse = await fetch(`/api/byok/capabilities/${providerName}`);
          if (capResponse.ok) {
            const capabilities = await capResponse.json();
            providerData[providerName] = {
              id: providerName,
              name: capabilities.provider || providerName,
              models: capabilities.models || [],
              max_context_length: capabilities.max_context_length || 0,
              supported_features: capabilities.supported_features || []
            };
          }
        }
        setProviders(providerData);
      }
    } catch (error) {
      console.error('Failed to fetch providers:', error);
    } finally {
      setLoading(false);
    }
  };

  const hasUserKey = (providerId: string) => {
    return userApiKeys.some(key => key.provider === providerId && key.is_active);
  };

  const getProviderStatus = (providerId: string) => {
    if (hasUserKey(providerId)) {
      return { status: 'byok', label: 'Your Key', color: 'text-green-600' };
    }
    return { status: 'default', label: 'Default', color: 'text-blue-600' };
  };

  const formatContextLength = (length: number) => {
    if (length >= 1000000) {
      return `${(length / 1000000).toFixed(1)}M`;
    } else if (length >= 1000) {
      return `${(length / 1000).toFixed(0)}K`;
    }
    return length.toString();
  };

  const selectedProviderData = selectedProvider ? providers[selectedProvider] : null;
  const availableModels = selectedProviderData?.models || [];

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="animate-pulse">
          <div className="h-4 bg-gray-200 rounded w-24 mb-2"></div>
          <div className="h-10 bg-gray-200 rounded"></div>
        </div>
        <div className="animate-pulse">
          <div className="h-4 bg-gray-200 rounded w-16 mb-2"></div>
          <div className="h-10 bg-gray-200 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Provider Selection */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          LLM Provider
        </label>
        <div className="relative">
          <button
            onClick={() => setShowProviderDropdown(!showProviderDropdown)}
            className="w-full flex items-center justify-between px-3 py-2 border border-gray-300 rounded-lg bg-white hover:bg-gray-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          >
            <div className="flex items-center space-x-2">
              {selectedProviderData ? (
                <>
                  <span className="font-medium">{selectedProviderData.name}</span>
                  <span className={`text-xs px-2 py-1 rounded-full bg-gray-100 ${getProviderStatus(selectedProvider!).color}`}>
                    {getProviderStatus(selectedProvider!).label}
                  </span>
                </>
              ) : (
                <span className="text-gray-500">Select a provider</span>
              )}
            </div>
            <ChevronDown className="w-4 h-4 text-gray-400" />
          </button>

          {showProviderDropdown && (
            <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg">
              <div className="py-1">
                {Object.values(providers).map((provider) => {
                  const status = getProviderStatus(provider.id);
                  return (
                    <button
                      key={provider.id}
                      onClick={() => {
                        onProviderChange(provider.id);
                        setShowProviderDropdown(false);
                        setShowModelDropdown(false);
                      }}
                      className="w-full px-3 py-2 text-left hover:bg-gray-50 flex items-center justify-between"
                    >
                      <div>
                        <div className="font-medium">{provider.name}</div>
                        <div className="text-xs text-gray-500">
                          {provider.models.length} models • {formatContextLength(provider.max_context_length)} tokens max
                        </div>
                      </div>
                      <div className="flex items-center space-x-2">
                        <span className={`text-xs px-2 py-1 rounded-full bg-gray-100 ${status.color}`}>
                          {status.label}
                        </span>
                        {hasUserKey(provider.id) && (
                          <CheckCircle className="w-4 h-4 text-green-500" />
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Model Selection */}
      {selectedProvider && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Model
          </label>
          <div className="relative">
            <button
              onClick={() => setShowModelDropdown(!showModelDropdown)}
              className="w-full flex items-center justify-between px-3 py-2 border border-gray-300 rounded-lg bg-white hover:bg-gray-50 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <div className="flex items-center space-x-2">
                {selectedModel ? (
                  <>
                    <span className="font-medium">
                      {availableModels.find(m => m.id === selectedModel)?.name || selectedModel}
                    </span>
                    <span className="text-xs text-gray-500">
                      {formatContextLength(availableModels.find(m => m.id === selectedModel)?.context_length || 0)} tokens
                    </span>
                  </>
                ) : (
                  <span className="text-gray-500">Select a model</span>
                )}
              </div>
              <ChevronDown className="w-4 h-4 text-gray-400" />
            </button>

            {showModelDropdown && (
              <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-y-auto">
                <div className="py-1">
                  {availableModels.map((model) => (
                    <button
                      key={model.id}
                      onClick={() => {
                        onModelChange(model.id);
                        setShowModelDropdown(false);
                      }}
                      className="w-full px-3 py-2 text-left hover:bg-gray-50"
                    >
                      <div className="font-medium">{model.name}</div>
                      <div className="text-xs text-gray-500 flex items-center space-x-4">
                        <span className="flex items-center space-x-1">
                          <Clock className="w-3 h-3" />
                          <span>{formatContextLength(model.context_length)} tokens</span>
                        </span>
                        {model.features.length > 0 && (
                          <span className="flex items-center space-x-1">
                            <Zap className="w-3 h-3" />
                            <span>{model.features.join(', ')}</span>
                          </span>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Provider Info */}
      {selectedProviderData && (
        <div className="bg-gray-50 rounded-lg p-4">
          <h4 className="font-medium text-gray-900 mb-2">Provider Information</h4>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-gray-500">Available Models:</span>
              <span className="ml-2 font-medium">{selectedProviderData.models.length}</span>
            </div>
            <div>
              <span className="text-gray-500">Max Context:</span>
              <span className="ml-2 font-medium">
                {formatContextLength(selectedProviderData.max_context_length)} tokens
              </span>
            </div>
            <div className="col-span-2">
              <span className="text-gray-500">Features:</span>
              <div className="mt-1 flex flex-wrap gap-1">
                {selectedProviderData.supported_features.map((feature) => (
                  <span
                    key={feature}
                    className="inline-flex items-center px-2 py-1 rounded-full text-xs bg-blue-100 text-blue-800"
                  >
                    {feature}
                  </span>
                ))}
              </div>
            </div>
          </div>
          
          {!hasUserKey(selectedProvider) && (
            <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <div className="flex items-start space-x-2">
                <DollarSign className="w-4 h-4 text-blue-600 mt-0.5" />
                <div className="text-sm">
                  <p className="text-blue-800 font-medium">Using Default API Key</p>
                  <p className="text-blue-600">
                    Add your own API key to avoid usage limits and get better performance.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ProviderSelector;
