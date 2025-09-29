"use client";

import React, { useState, useEffect } from 'react';
import { Plus, Key, Trash2, Edit3, Eye, EyeOff, CheckCircle, XCircle, AlertCircle } from 'lucide-react';

interface APIKey {
  id: string;
  provider: string;
  key_name: string;
  is_active: boolean;
  last_validated: string | null;
  created_at: string;
}

interface Provider {
  id: string;
  name: string;
  models: Array<{
    id: string;
    name: string;
    context_length: number;
  }>;
}

const APIKeyManager: React.FC = () => {
  const [apiKeys, setApiKeys] = useState<APIKey[]>([]);
  const [providers, setProviders] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newKey, setNewKey] = useState({
    provider: '',
    api_key: '',
    key_name: ''
  });
  const [validating, setValidating] = useState(false);
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});

  useEffect(() => {
    fetchAPIKeys();
    fetchProviders();
  }, []);

  const fetchAPIKeys = async () => {
    try {
      const response = await fetch('/api/byok/api-keys');
      if (response.ok) {
        const data = await response.json();
        setApiKeys(data.api_keys || []);
      }
    } catch (error) {
      console.error('Failed to fetch API keys:', error);
    }
  };

  const fetchProviders = async () => {
    try {
      const response = await fetch('/api/byok/providers');
      if (response.ok) {
        const data = await response.json();
        setProviders(data.providers || {});
      }
    } catch (error) {
      console.error('Failed to fetch providers:', error);
    } finally {
      setLoading(false);
    }
  };

  const validateAPIKey = async (provider: string, apiKey: string) => {
    setValidating(true);
    try {
      const response = await fetch('/api/byok/validate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          provider,
          api_key: apiKey
        })
      });
      
      const result = await response.json();
      return result.success;
    } catch (error) {
      console.error('API key validation failed:', error);
      return false;
    } finally {
      setValidating(false);
    }
  };

  const addAPIKey = async () => {
    if (!newKey.provider || !newKey.api_key) {
      alert('Please fill in all required fields');
      return;
    }

    const isValid = await validateAPIKey(newKey.provider, newKey.api_key);
    if (!isValid) {
      alert('Invalid API key. Please check your key and try again.');
      return;
    }

    try {
      const response = await fetch('/api/byok/api-keys', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(newKey)
      });

      if (response.ok) {
        setShowAddModal(false);
        setNewKey({ provider: '', api_key: '', key_name: '' });
        fetchAPIKeys();
      } else {
        alert('Failed to add API key');
      }
    } catch (error) {
      console.error('Failed to add API key:', error);
      alert('Failed to add API key');
    }
  };

  const deleteAPIKey = async (keyId: string) => {
    if (!confirm('Are you sure you want to delete this API key?')) {
      return;
    }

    try {
      const response = await fetch(`/api/byok/api-keys/${keyId}`, {
        method: 'DELETE'
      });

      if (response.ok) {
        fetchAPIKeys();
      } else {
        alert('Failed to delete API key');
      }
    } catch (error) {
      console.error('Failed to delete API key:', error);
      alert('Failed to delete API key');
    }
  };

  const toggleKeyVisibility = (keyId: string) => {
    setShowKey(prev => ({
      ...prev,
      [keyId]: !prev[keyId]
    }));
  };

  const getStatusIcon = (key: APIKey) => {
    if (key.is_active && key.last_validated) {
      return <CheckCircle className="w-4 h-4 text-green-500" />;
    } else if (!key.is_active) {
      return <XCircle className="w-4 h-4 text-red-500" />;
    } else {
      return <AlertCircle className="w-4 h-4 text-yellow-500" />;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">API Key Management</h2>
          <p className="text-gray-600">Manage your LLM provider API keys for BYOK (Bring Your Own Key)</p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center space-x-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>Add API Key</span>
        </button>
      </div>

      {/* API Keys List */}
      <div className="grid gap-4">
        {apiKeys.length === 0 ? (
          <div className="text-center py-12 bg-gray-50 rounded-lg">
            <Key className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No API Keys</h3>
            <p className="text-gray-600 mb-4">Add your first API key to get started with BYOK</p>
            <button
              onClick={() => setShowAddModal(true)}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
            >
              Add API Key
            </button>
          </div>
        ) : (
          apiKeys.map((key) => (
            <div key={key.id} className="bg-white border border-gray-200 rounded-lg p-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  {getStatusIcon(key)}
                  <div>
                    <h3 className="font-medium text-gray-900">
                      {key.key_name || `${key.provider} Key`}
                    </h3>
                    <p className="text-sm text-gray-600">
                      Provider: {key.provider.charAt(0).toUpperCase() + key.provider.slice(1)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => toggleKeyVisibility(key.id)}
                    className="p-2 text-gray-400 hover:text-gray-600 transition-colors"
                  >
                    {showKey[key.id] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                  <button
                    onClick={() => deleteAPIKey(key.id)}
                    className="p-2 text-red-400 hover:text-red-600 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
              
              <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Status:</span>
                  <span className={`ml-2 ${key.is_active ? 'text-green-600' : 'text-red-600'}`}>
                    {key.is_active ? 'Active' : 'Inactive'}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Last Validated:</span>
                  <span className="ml-2 text-gray-900">
                    {key.last_validated 
                      ? new Date(key.last_validated).toLocaleDateString()
                      : 'Never'
                    }
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Created:</span>
                  <span className="ml-2 text-gray-900">
                    {new Date(key.created_at).toLocaleDateString()}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Models Available:</span>
                  <span className="ml-2 text-gray-900">
                    {providers[key.provider]?.length || 0}
                  </span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Add API Key Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h3 className="text-lg font-medium text-gray-900 mb-4">Add New API Key</h3>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Provider
                </label>
                <select
                  value={newKey.provider}
                  onChange={(e) => setNewKey({ ...newKey, provider: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="">Select a provider</option>
                  {Object.keys(providers).map((provider) => (
                    <option key={provider} value={provider}>
                      {provider.charAt(0).toUpperCase() + provider.slice(1)}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  API Key
                </label>
                <input
                  type="password"
                  value={newKey.api_key}
                  onChange={(e) => setNewKey({ ...newKey, api_key: e.target.value })}
                  placeholder="Enter your API key"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Key Name (Optional)
                </label>
                <input
                  type="text"
                  value={newKey.key_name}
                  onChange={(e) => setNewKey({ ...newKey, key_name: e.target.value })}
                  placeholder="e.g., My OpenAI Key"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>

            <div className="flex justify-end space-x-3 mt-6">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-4 py-2 text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={addAPIKey}
                disabled={validating}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {validating ? 'Validating...' : 'Add Key'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default APIKeyManager;
