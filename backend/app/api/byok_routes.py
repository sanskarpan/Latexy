"""
BYOK (Bring Your Own Key) API routes for Phase 10
Handles user API key management and multi-provider configuration
"""

from typing import List, Dict, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from ..core.logging import get_logger
from ..database.connection import get_db
from ..services.api_key_service import api_key_service
from ..services.llm_provider_service import multi_provider_service, LLMRequest

logger = get_logger(__name__)

router = APIRouter(prefix="/byok", tags=["byok"])


# Pydantic models
class AddAPIKeyRequest(BaseModel):
    provider: str = Field(..., description="Provider name (openai, anthropic, openrouter)")
    api_key: str = Field(..., description="API key for the provider")
    key_name: Optional[str] = Field(None, description="Custom name for the API key")
    validate_key: bool = Field(True, description="Whether to validate the key with the provider")


class AddAPIKeyResponse(BaseModel):
    success: bool
    message: str
    key_id: Optional[str] = None
    provider: Optional[str] = None
    validated: Optional[bool] = None
    error: Optional[str] = None
    validation_details: Optional[Dict] = None


class APIKeyInfo(BaseModel):
    id: str
    provider: str
    key_name: str
    is_active: bool
    last_validated: Optional[str]
    created_at: str
    masked_key: str


class UserAPIKeysResponse(BaseModel):
    success: bool
    api_keys: List[APIKeyInfo]
    total_count: int


class ValidateAPIKeyRequest(BaseModel):
    provider: str
    api_key: str


class ValidateAPIKeyResponse(BaseModel):
    valid: bool
    provider: str
    capabilities: Optional[Dict] = None
    available_models: Optional[List[str]] = None
    validated_at: Optional[str] = None
    error: Optional[str] = None


class ProviderInfo(BaseModel):
    name: str
    display_name: str
    capabilities: Dict[str, Any]
    available_models: List[str]
    key_format: Dict[str, str]


class SupportedProvidersResponse(BaseModel):
    success: bool
    providers: List[ProviderInfo]
    total_count: int


class TestProviderRequest(BaseModel):
    provider: str


class TestProviderResponse(BaseModel):
    success: bool
    provider: str
    validation_details: Optional[Dict] = None
    tested_at: Optional[str] = None
    error: Optional[str] = None


class ProviderUsageStats(BaseModel):
    requests: int
    tokens: int
    cost: float
    errors: int
    last_used: Optional[str]


class UsageStatsResponse(BaseModel):
    success: bool
    usage_stats: Dict[str, ProviderUsageStats]
    total_requests: int
    total_cost: float


class GenerateWithProviderRequest(BaseModel):
    provider: str
    messages: List[Dict[str, str]]
    model: str
    max_tokens: Optional[int] = None
    temperature: float = 0.7
    stream: bool = False


class GenerateWithProviderResponse(BaseModel):
    success: bool
    content: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    cost: Optional[float] = None
    latency: Optional[float] = None
    error: Optional[str] = None


# API Key Management Endpoints
@router.post("/api-keys", response_model=AddAPIKeyResponse)
async def add_api_key(
    request: AddAPIKeyRequest,
    user_id: str = "f47ac10b-58cc-4372-a567-0e02b2c3d479",  # Demo UUID - TODO: Get from JWT token
    db: AsyncSession = Depends(get_db)
):
    """Add a new API key for a user."""
    try:
        result = await api_key_service.add_api_key(
            db=db,
            user_id=user_id,
            provider=request.provider,
            api_key=request.api_key,
            key_name=request.key_name,
            validate_key=request.validate_key
        )
        
        return AddAPIKeyResponse(**result)
        
    except Exception as e:
        logger.error(f"Error adding API key: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/api-keys", response_model=UserAPIKeysResponse)
async def get_user_api_keys(
    user_id: str = "f47ac10b-58cc-4372-a567-0e02b2c3d479",  # Demo UUID - TODO: Get from JWT token
    db: AsyncSession = Depends(get_db)
):
    """Get all API keys for the current user."""
    try:
        api_keys = await api_key_service.get_user_api_keys(db, user_id)
        
        return UserAPIKeysResponse(
            success=True,
            api_keys=[APIKeyInfo(**key) for key in api_keys],
            total_count=len(api_keys)
        )
        
    except Exception as e:
        logger.error(f"Error getting user API keys: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: str,
    user_id: str = "f47ac10b-58cc-4372-a567-0e02b2c3d479",  # Demo UUID - TODO: Get from JWT token
    db: AsyncSession = Depends(get_db)
):
    """Delete an API key."""
    try:
        result = await api_key_service.delete_api_key(db, user_id, key_id)
        
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["error"])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting API key: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Provider Management Endpoints
@router.get("/providers", response_model=SupportedProvidersResponse)
async def get_supported_providers():
    """Get list of supported providers with their capabilities."""
    try:
        providers = api_key_service.get_supported_providers()
        
        return SupportedProvidersResponse(
            success=True,
            providers=[ProviderInfo(**provider) for provider in providers],
            total_count=len(providers)
        )
        
    except Exception as e:
        logger.error(f"Error getting supported providers: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/validate", response_model=ValidateAPIKeyResponse)
async def validate_api_key(request: ValidateAPIKeyRequest):
    """Validate an API key with its provider."""
    try:
        result = await api_key_service.validate_api_key(request.provider, request.api_key)
        
        return ValidateAPIKeyResponse(
            valid=result["valid"],
            provider=request.provider,
            capabilities=result.get("capabilities"),
            available_models=result.get("available_models"),
            validated_at=result.get("validated_at"),
            error=result.get("error")
        )
        
    except Exception as e:
        logger.error(f"Error validating API key: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/test/{provider}", response_model=TestProviderResponse)
async def test_provider_connection(
    provider: str,
    user_id: str = "f47ac10b-58cc-4372-a567-0e02b2c3d479",  # Demo UUID - TODO: Get from JWT token
    db: AsyncSession = Depends(get_db)
):
    """Test connection to a user's configured provider."""
    try:
        result = await api_key_service.test_provider_connection(db, user_id, provider)
        
        return TestProviderResponse(**result)
        
    except Exception as e:
        logger.error(f"Error testing provider connection: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Usage and Statistics Endpoints
@router.get("/usage-stats", response_model=UsageStatsResponse)
async def get_usage_stats(
    user_id: str = "demo_user"  # TODO: Get from JWT token
):
    """Get usage statistics for user's providers."""
    try:
        stats = await api_key_service.get_provider_usage_stats(user_id)
        
        total_requests = sum(stat.get("requests", 0) for stat in stats.values())
        total_cost = sum(stat.get("cost", 0.0) for stat in stats.values())
        
        return UsageStatsResponse(
            success=True,
            usage_stats={
                provider: ProviderUsageStats(**stat_data)
                for provider, stat_data in stats.items()
            },
            total_requests=total_requests,
            total_cost=total_cost
        )
        
    except Exception as e:
        logger.error(f"Error getting usage stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# LLM Generation Endpoints
@router.post("/generate", response_model=GenerateWithProviderResponse)
async def generate_with_provider(
    request: GenerateWithProviderRequest,
    user_id: str = "f47ac10b-58cc-4372-a567-0e02b2c3d479",  # Demo UUID - TODO: Get from JWT token
    db: AsyncSession = Depends(get_db)
):
    """Generate content using a specific provider."""
    try:
        # Load user providers
        await api_key_service.load_user_providers(db, user_id)
        
        # Create LLM request
        llm_request = LLMRequest(
            messages=request.messages,
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stream=request.stream,
            user_id=user_id
        )
        
        # Generate with specific provider
        provider_name = f"{request.provider}_{user_id}"
        response = await multi_provider_service.generate(
            llm_request, 
            provider_name=provider_name,
            fallback=False
        )
        
        return GenerateWithProviderResponse(
            success=True,
            content=response.content,
            model=response.model,
            provider=response.provider,
            usage=response.usage,
            cost=response.cost,
            latency=response.latency
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating with provider: {e}")
        return GenerateWithProviderResponse(
            success=False,
            error=str(e)
        )


# System Health and Monitoring
@router.get("/system/health")
async def get_system_health():
    """Get health status of the multi-provider system."""
    try:
        provider_health = multi_provider_service.get_provider_health()
        usage_stats = multi_provider_service.get_usage_stats()
        
        return {
            "success": True,
            "provider_health": provider_health,
            "total_providers": len(multi_provider_service.providers),
            "default_provider": multi_provider_service.default_provider,
            "total_requests": sum(stats.get("requests", 0) for stats in usage_stats.values()),
            "total_cost": sum(stats.get("cost", 0.0) for stats in usage_stats.values()),
            "timestamp": "2024-01-01T00:00:00Z"  # TODO: Use actual timestamp
        }
        
    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Provider Configuration Management
@router.post("/load-providers")
async def load_user_providers(
    user_id: str = "f47ac10b-58cc-4372-a567-0e02b2c3d479",  # Demo UUID - TODO: Get from JWT token
    db: AsyncSession = Depends(get_db)
):
    """Load all user providers into the service."""
    try:
        await api_key_service.load_user_providers(db, user_id)
        
        # Get loaded providers
        user_provider_names = [
            name for name in multi_provider_service.providers.keys()
            if name.endswith(f"_{user_id}")
        ]
        
        return {
            "success": True,
            "message": f"Loaded {len(user_provider_names)} providers",
            "loaded_providers": [name.replace(f"_{user_id}", "") for name in user_provider_names]
        }
        
    except Exception as e:
        logger.error(f"Error loading user providers: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/models/{provider}")
async def get_provider_models(provider: str):
    """Get available models for a specific provider."""
    try:
        if provider not in api_key_service.provider_classes:
            raise HTTPException(status_code=404, detail=f"Provider {provider} not supported")
        
        provider_class = api_key_service.provider_classes[provider]
        temp_instance = provider_class("dummy_key")
        models = temp_instance.get_available_models()
        
        return {
            "success": True,
            "provider": provider,
            "models": models,
            "total_count": len(models)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting provider models: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/capabilities/{provider}")
async def get_provider_capabilities(provider: str):
    """Get capabilities for a specific provider."""
    try:
        if provider not in api_key_service.provider_classes:
            raise HTTPException(status_code=404, detail=f"Provider {provider} not supported")
        
        provider_class = api_key_service.provider_classes[provider]
        temp_instance = provider_class("dummy_key")
        capabilities = temp_instance.get_capabilities()
        
        return {
            "success": True,
            "provider": provider,
            "capabilities": {
                "max_context_length": capabilities.max_context_length,
                "supports_streaming": capabilities.supports_streaming,
                "supports_function_calling": capabilities.supports_function_calling,
                "supports_vision": capabilities.supports_vision,
                "cost_per_1k_input_tokens": capabilities.cost_per_1k_input_tokens,
                "cost_per_1k_output_tokens": capabilities.cost_per_1k_output_tokens,
                "rate_limit_rpm": capabilities.rate_limit_rpm,
                "rate_limit_tpm": capabilities.rate_limit_tpm,
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting provider capabilities: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
