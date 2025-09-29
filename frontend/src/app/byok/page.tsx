"use client";

import React from 'react';
import { Key, Shield, Zap, DollarSign } from 'lucide-react';
import APIKeyManager from '@/components/byok/APIKeyManager';

const BYOKPage: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center space-x-3 mb-4">
            <div className="p-2 bg-blue-100 rounded-lg">
              <Key className="w-6 h-6 text-blue-600" />
            </div>
            <h1 className="text-3xl font-bold text-gray-900">
              Bring Your Own Key (BYOK)
            </h1>
          </div>
          <p className="text-lg text-gray-600 max-w-3xl">
            Use your own LLM provider API keys for unlimited access, better performance, 
            and full control over your AI-powered resume optimization.
          </p>
        </div>

        {/* Benefits */}
        <div className="grid md:grid-cols-3 gap-6 mb-8">
          <div className="bg-white rounded-lg p-6 border border-gray-200">
            <div className="flex items-center space-x-3 mb-4">
              <div className="p-2 bg-green-100 rounded-lg">
                <DollarSign className="w-5 h-5 text-green-600" />
              </div>
              <h3 className="font-semibold text-gray-900">Cost Control</h3>
            </div>
            <p className="text-gray-600">
              Pay only for what you use directly to the provider. No markup, no limits.
            </p>
          </div>

          <div className="bg-white rounded-lg p-6 border border-gray-200">
            <div className="flex items-center space-x-3 mb-4">
              <div className="p-2 bg-purple-100 rounded-lg">
                <Zap className="w-5 h-5 text-purple-600" />
              </div>
              <h3 className="font-semibold text-gray-900">Better Performance</h3>
            </div>
            <p className="text-gray-600">
              Direct API access means faster response times and higher rate limits.
            </p>
          </div>

          <div className="bg-white rounded-lg p-6 border border-gray-200">
            <div className="flex items-center space-x-3 mb-4">
              <div className="p-2 bg-blue-100 rounded-lg">
                <Shield className="w-5 h-5 text-blue-600" />
              </div>
              <h3 className="font-semibold text-gray-900">Privacy & Security</h3>
            </div>
            <p className="text-gray-600">
              Your API keys are encrypted and stored securely. Full data privacy.
            </p>
          </div>
        </div>

        {/* Supported Providers */}
        <div className="bg-white rounded-lg border border-gray-200 p-6 mb-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Supported Providers</h2>
          <div className="grid md:grid-cols-3 gap-4">
            <div className="flex items-center space-x-3 p-3 bg-gray-50 rounded-lg">
              <div className="w-8 h-8 bg-green-500 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-sm">O</span>
              </div>
              <div>
                <div className="font-medium">OpenAI</div>
                <div className="text-sm text-gray-500">GPT-4, GPT-3.5</div>
              </div>
            </div>
            
            <div className="flex items-center space-x-3 p-3 bg-gray-50 rounded-lg">
              <div className="w-8 h-8 bg-orange-500 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-sm">A</span>
              </div>
              <div>
                <div className="font-medium">Anthropic</div>
                <div className="text-sm text-gray-500">Claude 3.5, Claude 3</div>
              </div>
            </div>
            
            <div className="flex items-center space-x-3 p-3 bg-gray-50 rounded-lg">
              <div className="w-8 h-8 bg-purple-500 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-sm">OR</span>
              </div>
              <div>
                <div className="font-medium">OpenRouter</div>
                <div className="text-sm text-gray-500">Multiple Models</div>
              </div>
            </div>
          </div>
        </div>

        {/* API Key Manager */}
        <APIKeyManager />

        {/* How it Works */}
        <div className="bg-white rounded-lg border border-gray-200 p-6 mt-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">How It Works</h2>
          <div className="grid md:grid-cols-4 gap-6">
            <div className="text-center">
              <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-3">
                <span className="text-blue-600 font-bold">1</span>
              </div>
              <h3 className="font-medium mb-2">Get API Key</h3>
              <p className="text-sm text-gray-600">
                Sign up with your preferred LLM provider and get an API key
              </p>
            </div>
            
            <div className="text-center">
              <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-3">
                <span className="text-blue-600 font-bold">2</span>
              </div>
              <h3 className="font-medium mb-2">Add to Latexy</h3>
              <p className="text-sm text-gray-600">
                Securely add your API key to your Latexy account
              </p>
            </div>
            
            <div className="text-center">
              <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-3">
                <span className="text-blue-600 font-bold">3</span>
              </div>
              <h3 className="font-medium mb-2">Select Provider</h3>
              <p className="text-sm text-gray-600">
                Choose your provider and model when optimizing resumes
              </p>
            </div>
            
            <div className="text-center">
              <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-3">
                <span className="text-blue-600 font-bold">4</span>
              </div>
              <h3 className="font-medium mb-2">Optimize</h3>
              <p className="text-sm text-gray-600">
                Enjoy unlimited, fast resume optimization with your own key
              </p>
            </div>
          </div>
        </div>

        {/* Security Notice */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6 mt-8">
          <div className="flex items-start space-x-3">
            <Shield className="w-6 h-6 text-blue-600 mt-0.5" />
            <div>
              <h3 className="font-semibold text-blue-900 mb-2">Security & Privacy</h3>
              <p className="text-blue-800 mb-2">
                Your API keys are encrypted using industry-standard AES-256 encryption before being stored. 
                We never log or store your API requests or responses.
              </p>
              <ul className="text-sm text-blue-700 space-y-1">
                <li>• API keys are encrypted at rest and in transit</li>
                <li>• Keys are only decrypted when making API calls on your behalf</li>
                <li>• You can revoke access at any time by deleting your keys</li>
                <li>• We recommend using API keys with minimal required permissions</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default BYOKPage;
