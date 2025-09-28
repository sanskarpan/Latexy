"""
Multi-Provider LLM Service for Phase 10 - BYOK System
Supports multiple LLM providers with user-supplied API keys
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta

import openai
import httpx
from openai import AsyncOpenAI

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OPENROUTER = "openrouter"


@dataclass
class ProviderCapabilities:
    """Provider capabilities and limitations"""
    max_context_length: int
    supports_streaming: bool
    supports_function_calling: bool
    supports_vision: bool
    cost_per_1k_input_tokens: float
    cost_per_1k_output_tokens: float
    rate_limit_rpm: int  # requests per minute
    rate_limit_tpm: int  # tokens per minute


@dataclass
class LLMRequest:
    """Standardized LLM request"""
    messages: List[Dict[str, str]]
    model: str
    max_tokens: Optional[int] = None
    temperature: float = 0.7
    stream: bool = False
    functions: Optional[List[Dict]] = None
    user_id: Optional[str] = None
    provider_specific_params: Optional[Dict] = None


@dataclass
class LLMResponse:
    """Standardized LLM response"""
    content: str
    model: str
    provider: str
    usage: Dict[str, int]
    cost: float
    latency: float
    finish_reason: str
    raw_response: Optional[Dict] = None


class BaseLLMProvider(ABC):
    """Base class for all LLM providers"""
    
    def __init__(self, api_key: str, provider_config: Optional[Dict] = None):
        self.api_key = api_key
        self.provider_config = provider_config or {}
        self.provider_name = self.__class__.__name__.lower().replace('provider', '')
    
    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response from the LLM"""
        pass
    
    @abstractmethod
    async def validate_api_key(self) -> bool:
        """Validate the API key"""
        pass
    
    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """Get provider capabilities"""
        pass
    
    @abstractmethod
    def get_available_models(self) -> List[str]:
        """Get list of available models"""
        pass
    
    def calculate_cost(self, usage: Dict[str, int], model: str) -> float:
        """Calculate cost based on usage"""
        capabilities = self.get_capabilities()
        input_tokens = usage.get('prompt_tokens', 0)
        output_tokens = usage.get('completion_tokens', 0)
        
        input_cost = (input_tokens / 1000) * capabilities.cost_per_1k_input_tokens
        output_cost = (output_tokens / 1000) * capabilities.cost_per_1k_output_tokens
        
        return input_cost + output_cost


class OpenAIProvider(BaseLLMProvider):
    """OpenAI provider implementation"""
    
    def __init__(self, api_key: str, provider_config: Optional[Dict] = None):
        super().__init__(api_key, provider_config)
        self.client = AsyncOpenAI(api_key=api_key)
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        start_time = time.time()
        
        try:
            # Prepare OpenAI-specific parameters
            params = {
                "model": request.model,
                "messages": request.messages,
                "temperature": request.temperature,
                "stream": request.stream,
            }
            
            if request.max_tokens:
                params["max_tokens"] = request.max_tokens
            
            if request.functions:
                params["functions"] = request.functions
            
            # Add provider-specific parameters
            if request.provider_specific_params:
                params.update(request.provider_specific_params)
            
            response = await self.client.chat.completions.create(**params)
            
            latency = time.time() - start_time
            
            # Extract response data
            content = response.choices[0].message.content or ""
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            
            cost = self.calculate_cost(usage, request.model)
            
            return LLMResponse(
                content=content,
                model=response.model,
                provider="openai",
                usage=usage,
                cost=cost,
                latency=latency,
                finish_reason=response.choices[0].finish_reason,
                raw_response=response.model_dump() if hasattr(response, 'model_dump') else None
            )
            
        except Exception as e:
            logger.error(f"OpenAI generation error: {e}")
            raise
    
    async def validate_api_key(self) -> bool:
        try:
            # Test with a minimal request
            await self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1
            )
            return True
        except Exception as e:
            logger.error(f"OpenAI API key validation failed: {e}")
            return False
    
    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            max_context_length=128000,  # GPT-4 Turbo
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision=True,
            cost_per_1k_input_tokens=0.01,  # GPT-4 Turbo pricing
            cost_per_1k_output_tokens=0.03,
            rate_limit_rpm=10000,
            rate_limit_tpm=2000000
        )
    
    def get_available_models(self) -> List[str]:
        return [
            "gpt-4-turbo-preview",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-16k"
        ]


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude provider implementation"""
    
    def __init__(self, api_key: str, provider_config: Optional[Dict] = None):
        super().__init__(api_key, provider_config)
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        start_time = time.time()
        
        try:
            # Convert OpenAI format to Anthropic format
            system_message = ""
            messages = []
            
            for msg in request.messages:
                if msg["role"] == "system":
                    system_message = msg["content"]
                else:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
            
            params = {
                "model": request.model,
                "messages": messages,
                "max_tokens": request.max_tokens or 4096,
                "temperature": request.temperature,
            }
            
            if system_message:
                params["system"] = system_message
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    headers=self.headers,
                    json=params,
                    timeout=60.0
                )
                response.raise_for_status()
                data = response.json()
            
            latency = time.time() - start_time
            
            # Extract response data
            content = data["content"][0]["text"] if data.get("content") else ""
            usage = {
                "prompt_tokens": data.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
                "total_tokens": data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0),
            }
            
            cost = self.calculate_cost(usage, request.model)
            
            return LLMResponse(
                content=content,
                model=data.get("model", request.model),
                provider="anthropic",
                usage=usage,
                cost=cost,
                latency=latency,
                finish_reason=data.get("stop_reason", "stop"),
                raw_response=data
            )
            
        except Exception as e:
            logger.error(f"Anthropic generation error: {e}")
            raise
    
    async def validate_api_key(self) -> bool:
        try:
            params = {
                "model": "claude-3-haiku-20240307",
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 1
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    headers=self.headers,
                    json=params,
                    timeout=30.0
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Anthropic API key validation failed: {e}")
            return False
    
    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            max_context_length=200000,  # Claude 3
            supports_streaming=True,
            supports_function_calling=False,
            supports_vision=True,
            cost_per_1k_input_tokens=0.0025,  # Claude 3 Haiku pricing
            cost_per_1k_output_tokens=0.0125,
            rate_limit_rpm=5000,
            rate_limit_tpm=1000000
        )
    
    def get_available_models(self) -> List[str]:
        return [
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter provider implementation (supports multiple models)"""
    
    def __init__(self, api_key: str, provider_config: Optional[Dict] = None):
        super().__init__(api_key, provider_config)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1"
        )
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        start_time = time.time()
        
        try:
            params = {
                "model": request.model,
                "messages": request.messages,
                "temperature": request.temperature,
            }
            
            if request.max_tokens:
                params["max_tokens"] = request.max_tokens
            
            response = await self.client.chat.completions.create(**params)
            
            latency = time.time() - start_time
            
            content = response.choices[0].message.content or ""
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            
            cost = self.calculate_cost(usage, request.model)
            
            return LLMResponse(
                content=content,
                model=response.model,
                provider="openrouter",
                usage=usage,
                cost=cost,
                latency=latency,
                finish_reason=response.choices[0].finish_reason,
                raw_response=response.model_dump() if hasattr(response, 'model_dump') else None
            )
            
        except Exception as e:
            logger.error(f"OpenRouter generation error: {e}")
            raise
    
    async def validate_api_key(self) -> bool:
        try:
            await self.client.chat.completions.create(
                model="openai/gpt-3.5-turbo",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1
            )
            return True
        except Exception as e:
            logger.error(f"OpenRouter API key validation failed: {e}")
            return False
    
    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            max_context_length=128000,
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision=False,
            cost_per_1k_input_tokens=0.005,  # Average pricing
            cost_per_1k_output_tokens=0.015,
            rate_limit_rpm=1000,
            rate_limit_tpm=100000
        )
    
    def get_available_models(self) -> List[str]:
        return [
            "openai/gpt-4-turbo-preview",
            "openai/gpt-4",
            "openai/gpt-3.5-turbo",
            "anthropic/claude-3-opus",
            "anthropic/claude-3-sonnet",
            "anthropic/claude-3-haiku",
            "meta-llama/llama-2-70b-chat",
            "mistralai/mistral-7b-instruct"
        ]


class MultiProviderLLMService:
    """Main service for managing multiple LLM providers"""
    
    def __init__(self):
        self.providers: Dict[str, BaseLLMProvider] = {}
        self.default_provider = None
        self.usage_stats: Dict[str, Dict] = {}
        self.rate_limiters: Dict[str, Dict] = {}
    
    def add_provider(self, provider_name: str, provider: BaseLLMProvider, is_default: bool = False):
        """Add a provider to the service"""
        self.providers[provider_name] = provider
        if is_default or not self.default_provider:
            self.default_provider = provider_name
        
        # Initialize usage stats
        self.usage_stats[provider_name] = {
            "requests": 0,
            "tokens": 0,
            "cost": 0.0,
            "errors": 0,
            "last_used": None
        }
        
        logger.info(f"Added LLM provider: {provider_name}")
    
    def remove_provider(self, provider_name: str):
        """Remove a provider from the service"""
        if provider_name in self.providers:
            del self.providers[provider_name]
            if self.default_provider == provider_name:
                self.default_provider = next(iter(self.providers.keys())) if self.providers else None
            logger.info(f"Removed LLM provider: {provider_name}")
    
    def get_provider(self, provider_name: Optional[str] = None) -> BaseLLMProvider:
        """Get a specific provider or the default one"""
        if not provider_name:
            provider_name = self.default_provider
        
        if not provider_name or provider_name not in self.providers:
            raise ValueError(f"Provider {provider_name} not found")
        
        return self.providers[provider_name]
    
    async def generate(self, request: LLMRequest, provider_name: Optional[str] = None, fallback: bool = True) -> LLMResponse:
        """Generate response with optional fallback to other providers"""
        provider_name = provider_name or self.default_provider
        
        if not provider_name:
            raise ValueError("No provider specified and no default provider set")
        
        try:
            provider = self.get_provider(provider_name)
            response = await provider.generate(request)
            
            # Update usage stats
            self.update_usage_stats(provider_name, response)
            
            return response
            
        except Exception as e:
            logger.error(f"Error with provider {provider_name}: {e}")
            
            # Update error stats
            if provider_name in self.usage_stats:
                self.usage_stats[provider_name]["errors"] += 1
            
            # Try fallback if enabled
            if fallback and len(self.providers) > 1:
                for fallback_provider in self.providers.keys():
                    if fallback_provider != provider_name:
                        try:
                            logger.info(f"Falling back to provider: {fallback_provider}")
                            provider = self.get_provider(fallback_provider)
                            response = await provider.generate(request)
                            self.update_usage_stats(fallback_provider, response)
                            return response
                        except Exception as fallback_error:
                            logger.error(f"Fallback provider {fallback_provider} also failed: {fallback_error}")
                            continue
            
            # If all providers failed, raise the original error
            raise e
    
    def update_usage_stats(self, provider_name: str, response: LLMResponse):
        """Update usage statistics for a provider"""
        if provider_name in self.usage_stats:
            stats = self.usage_stats[provider_name]
            stats["requests"] += 1
            stats["tokens"] += response.usage.get("total_tokens", 0)
            stats["cost"] += response.cost
            stats["last_used"] = datetime.now().isoformat()
    
    async def validate_provider(self, provider_name: str) -> bool:
        """Validate a provider's API key"""
        try:
            provider = self.get_provider(provider_name)
            return await provider.validate_api_key()
        except Exception as e:
            logger.error(f"Provider validation failed for {provider_name}: {e}")
            return False
    
    def get_provider_capabilities(self, provider_name: str) -> ProviderCapabilities:
        """Get capabilities for a specific provider"""
        provider = self.get_provider(provider_name)
        return provider.get_capabilities()
    
    def get_available_models(self, provider_name: str) -> List[str]:
        """Get available models for a specific provider"""
        provider = self.get_provider(provider_name)
        return provider.get_available_models()
    
    def get_usage_stats(self) -> Dict[str, Dict]:
        """Get usage statistics for all providers"""
        return self.usage_stats.copy()
    
    def get_provider_health(self) -> Dict[str, Dict]:
        """Get health status for all providers"""
        health = {}
        for provider_name in self.providers.keys():
            stats = self.usage_stats.get(provider_name, {})
            health[provider_name] = {
                "status": "healthy" if stats.get("errors", 0) < 5 else "degraded",
                "requests": stats.get("requests", 0),
                "error_rate": stats.get("errors", 0) / max(stats.get("requests", 1), 1),
                "last_used": stats.get("last_used"),
                "total_cost": stats.get("cost", 0.0)
            }
        return health


# Global service instance
multi_provider_service = MultiProviderLLMService()

# Initialize default provider if available
if settings.OPENAI_API_KEY:
    multi_provider_service.add_provider(
        "openai_default",
        OpenAIProvider(settings.OPENAI_API_KEY),
        is_default=True
    )
