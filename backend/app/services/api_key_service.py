"""
API Key Management Service for Phase 10 - BYOK System
Handles secure storage, validation, and management of user API keys
"""

import asyncio
import base64
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.logging import get_logger
from ..database.models import User, UserAPIKey
from .llm_provider_service import (
    multi_provider_service, 
    OpenAIProvider, 
    AnthropicProvider, 
    OpenRouterProvider,
    LLMProvider
)

logger = get_logger(__name__)


class APIKeyEncryption:
    """Handles encryption and decryption of API keys"""
    
    def __init__(self, encryption_key: Optional[str] = None):
        if encryption_key:
            self.fernet = Fernet(encryption_key.encode())
        else:
            # Generate a key from settings or create a new one
            key = settings.API_KEY_ENCRYPTION_KEY or Fernet.generate_key()
            if isinstance(key, str):
                key = key.encode()
            self.fernet = Fernet(key)
    
    def encrypt(self, api_key: str) -> str:
        """Encrypt an API key"""
        encrypted = self.fernet.encrypt(api_key.encode())
        return base64.b64encode(encrypted).decode()
    
    def decrypt(self, encrypted_key: str) -> str:
        """Decrypt an API key"""
        encrypted_bytes = base64.b64decode(encrypted_key.encode())
        decrypted = self.fernet.decrypt(encrypted_bytes)
        return decrypted.decode()


class APIKeyService:
    """Service for managing user API keys"""
    
    def __init__(self):
        self.encryption = APIKeyEncryption()
        self.provider_classes = {
            LLMProvider.OPENAI.value: OpenAIProvider,
            LLMProvider.ANTHROPIC.value: AnthropicProvider,
            LLMProvider.OPENROUTER.value: OpenRouterProvider,
        }
    
    async def add_api_key(
        self, 
        db: AsyncSession, 
        user_id: str, 
        provider: str, 
        api_key: str, 
        key_name: Optional[str] = None,
        validate_key: bool = True
    ) -> Dict[str, any]:
        """Add a new API key for a user"""
        try:
            # Validate provider
            if provider not in self.provider_classes:
                return {
                    "success": False,
                    "error": f"Unsupported provider: {provider}",
                    "supported_providers": list(self.provider_classes.keys())
                }
            
            # Validate API key if requested
            if validate_key:
                validation_result = await self.validate_api_key(provider, api_key)
                if not validation_result["valid"]:
                    return {
                        "success": False,
                        "error": f"API key validation failed: {validation_result.get('error', 'Invalid key')}",
                        "validation_details": validation_result
                    }
            
            # Check if user already has a key for this provider
            existing_key = await db.execute(
                select(UserAPIKey).where(
                    UserAPIKey.user_id == user_id,
                    UserAPIKey.provider == provider,
                    UserAPIKey.is_active == True
                )
            )
            existing = existing_key.scalar_one_or_none()
            
            if existing:
                # Update existing key
                existing.encrypted_key = self.encryption.encrypt(api_key)
                existing.key_name = key_name or existing.key_name
                existing.last_validated = datetime.utcnow() if validate_key else None
                await db.commit()
                
                # Update provider in service
                await self.update_provider_in_service(user_id, provider, api_key)
                
                return {
                    "success": True,
                    "message": "API key updated successfully",
                    "key_id": existing.id,
                    "provider": provider,
                    "validated": validate_key
                }
            else:
                # Create new key
                encrypted_key = self.encryption.encrypt(api_key)
                
                new_key = UserAPIKey(
                    user_id=user_id,
                    provider=provider,
                    encrypted_key=encrypted_key,
                    key_name=key_name or f"{provider.title()} API Key",
                    is_active=True,
                    last_validated=datetime.utcnow() if validate_key else None
                )
                
                db.add(new_key)
                await db.commit()
                await db.refresh(new_key)
                
                # Add provider to service
                await self.update_provider_in_service(user_id, provider, api_key)
                
                return {
                    "success": True,
                    "message": "API key added successfully",
                    "key_id": new_key.id,
                    "provider": provider,
                    "validated": validate_key
                }
                
        except Exception as e:
            logger.error(f"Error adding API key: {e}")
            await db.rollback()
            return {
                "success": False,
                "error": f"Failed to add API key: {str(e)}"
            }
    
    async def get_user_api_keys(self, db: AsyncSession, user_id: str) -> List[Dict[str, any]]:
        """Get all API keys for a user (without decrypting them)"""
        try:
            result = await db.execute(
                select(UserAPIKey).where(
                    UserAPIKey.user_id == user_id,
                    UserAPIKey.is_active == True
                ).order_by(UserAPIKey.created_at.desc())
            )
            keys = result.scalars().all()
            
            return [
                {
                    "id": key.id,
                    "provider": key.provider,
                    "key_name": key.key_name,
                    "is_active": key.is_active,
                    "last_validated": key.last_validated.isoformat() if key.last_validated else None,
                    "created_at": key.created_at.isoformat(),
                    "masked_key": self.mask_api_key(key.provider)
                }
                for key in keys
            ]
            
        except Exception as e:
            logger.error(f"Error getting user API keys: {e}")
            return []
    
    async def delete_api_key(self, db: AsyncSession, user_id: str, key_id: str) -> Dict[str, any]:
        """Delete an API key"""
        try:
            result = await db.execute(
                select(UserAPIKey).where(
                    UserAPIKey.id == key_id,
                    UserAPIKey.user_id == user_id
                )
            )
            key = result.scalar_one_or_none()
            
            if not key:
                return {
                    "success": False,
                    "error": "API key not found"
                }
            
            # Remove from database
            await db.delete(key)
            await db.commit()
            
            # Remove provider from service
            provider_name = f"{key.provider}_{user_id}"
            multi_provider_service.remove_provider(provider_name)
            
            return {
                "success": True,
                "message": "API key deleted successfully",
                "provider": key.provider
            }
            
        except Exception as e:
            logger.error(f"Error deleting API key: {e}")
            await db.rollback()
            return {
                "success": False,
                "error": f"Failed to delete API key: {str(e)}"
            }
    
    async def validate_api_key(self, provider: str, api_key: str) -> Dict[str, any]:
        """Validate an API key with the provider"""
        try:
            if provider not in self.provider_classes:
                return {
                    "valid": False,
                    "error": f"Unsupported provider: {provider}"
                }
            
            provider_class = self.provider_classes[provider]
            provider_instance = provider_class(api_key)
            
            is_valid = await provider_instance.validate_api_key()
            
            if is_valid:
                capabilities = provider_instance.get_capabilities()
                models = provider_instance.get_available_models()
                
                return {
                    "valid": True,
                    "provider": provider,
                    "capabilities": {
                        "max_context_length": capabilities.max_context_length,
                        "supports_streaming": capabilities.supports_streaming,
                        "supports_function_calling": capabilities.supports_function_calling,
                        "cost_per_1k_input_tokens": capabilities.cost_per_1k_input_tokens,
                        "cost_per_1k_output_tokens": capabilities.cost_per_1k_output_tokens,
                    },
                    "available_models": models[:10],  # Limit to first 10 models
                    "validated_at": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "valid": False,
                    "error": "API key validation failed with provider"
                }
                
        except Exception as e:
            logger.error(f"Error validating API key for {provider}: {e}")
            return {
                "valid": False,
                "error": f"Validation error: {str(e)}"
            }
    
    async def get_user_provider(self, db: AsyncSession, user_id: str, provider: str) -> Optional[str]:
        """Get decrypted API key for a user's provider"""
        try:
            result = await db.execute(
                select(UserAPIKey).where(
                    UserAPIKey.user_id == user_id,
                    UserAPIKey.provider == provider,
                    UserAPIKey.is_active == True
                )
            )
            key = result.scalar_one_or_none()
            
            if key:
                return self.encryption.decrypt(key.encrypted_key)
            return None
            
        except Exception as e:
            logger.error(f"Error getting user provider key: {e}")
            return None
    
    async def update_provider_in_service(self, user_id: str, provider: str, api_key: str):
        """Update or add provider in the multi-provider service"""
        try:
            provider_name = f"{provider}_{user_id}"
            provider_class = self.provider_classes[provider]
            provider_instance = provider_class(api_key)
            
            # Remove existing provider if it exists
            if provider_name in multi_provider_service.providers:
                multi_provider_service.remove_provider(provider_name)
            
            # Add new provider
            multi_provider_service.add_provider(provider_name, provider_instance)
            
            logger.info(f"Updated provider {provider} for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error updating provider in service: {e}")
    
    async def load_user_providers(self, db: AsyncSession, user_id: str):
        """Load all active providers for a user into the service"""
        try:
            result = await db.execute(
                select(UserAPIKey).where(
                    UserAPIKey.user_id == user_id,
                    UserAPIKey.is_active == True
                )
            )
            keys = result.scalars().all()
            
            for key in keys:
                try:
                    api_key = self.encryption.decrypt(key.encrypted_key)
                    await self.update_provider_in_service(user_id, key.provider, api_key)
                except Exception as e:
                    logger.error(f"Error loading provider {key.provider} for user {user_id}: {e}")
            
            logger.info(f"Loaded {len(keys)} providers for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error loading user providers: {e}")
    
    def mask_api_key(self, provider: str) -> str:
        """Return a masked version of the API key for display"""
        masks = {
            "openai": "sk-...****",
            "anthropic": "sk-ant-...****",
            "openrouter": "sk-or-...****",
            "gemini": "AI...****"
        }
        return masks.get(provider, "****...****")
    
    async def get_provider_usage_stats(self, user_id: str) -> Dict[str, Dict]:
        """Get usage statistics for user's providers"""
        try:
            user_providers = {}
            all_stats = multi_provider_service.get_usage_stats()
            
            for provider_name, stats in all_stats.items():
                if provider_name.endswith(f"_{user_id}"):
                    provider_type = provider_name.replace(f"_{user_id}", "")
                    user_providers[provider_type] = stats
            
            return user_providers
            
        except Exception as e:
            logger.error(f"Error getting provider usage stats: {e}")
            return {}
    
    async def test_provider_connection(self, db: AsyncSession, user_id: str, provider: str) -> Dict[str, any]:
        """Test connection to a user's provider"""
        try:
            api_key = await self.get_user_provider(db, user_id, provider)
            if not api_key:
                return {
                    "success": False,
                    "error": "No API key found for this provider"
                }
            
            validation_result = await self.validate_api_key(provider, api_key)
            
            if validation_result["valid"]:
                # Update last_validated timestamp
                await db.execute(
                    update(UserAPIKey).where(
                        UserAPIKey.user_id == user_id,
                        UserAPIKey.provider == provider,
                        UserAPIKey.is_active == True
                    ).values(last_validated=datetime.utcnow())
                )
                await db.commit()
            
            return {
                "success": validation_result["valid"],
                "provider": provider,
                "validation_details": validation_result,
                "tested_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error testing provider connection: {e}")
            return {
                "success": False,
                "error": f"Connection test failed: {str(e)}"
            }
    
    def get_supported_providers(self) -> List[Dict[str, any]]:
        """Get list of supported providers with their details"""
        providers = []
        
        for provider_enum in LLMProvider:
            provider_name = provider_enum.value
            if provider_name in self.provider_classes:
                provider_class = self.provider_classes[provider_name]
                
                # Create a temporary instance to get capabilities (without API key)
                try:
                    temp_instance = provider_class("dummy_key")
                    capabilities = temp_instance.get_capabilities()
                    models = temp_instance.get_available_models()
                    
                    providers.append({
                        "name": provider_name,
                        "display_name": provider_name.title(),
                        "capabilities": {
                            "max_context_length": capabilities.max_context_length,
                            "supports_streaming": capabilities.supports_streaming,
                            "supports_function_calling": capabilities.supports_function_calling,
                            "supports_vision": capabilities.supports_vision,
                            "cost_per_1k_input_tokens": capabilities.cost_per_1k_input_tokens,
                            "cost_per_1k_output_tokens": capabilities.cost_per_1k_output_tokens,
                        },
                        "available_models": models,
                        "key_format": self.get_key_format_info(provider_name)
                    })
                except Exception as e:
                    logger.error(f"Error getting provider info for {provider_name}: {e}")
        
        return providers
    
    def get_key_format_info(self, provider: str) -> Dict[str, str]:
        """Get API key format information for a provider"""
        formats = {
            "openai": {
                "prefix": "sk-",
                "length": "51 characters",
                "example": "sk-1234567890abcdef...",
                "description": "OpenAI API keys start with 'sk-' and are 51 characters long"
            },
            "anthropic": {
                "prefix": "sk-ant-",
                "length": "variable",
                "example": "sk-ant-api03-1234567890abcdef...",
                "description": "Anthropic API keys start with 'sk-ant-'"
            },
            "openrouter": {
                "prefix": "sk-or-",
                "length": "variable",
                "example": "sk-or-1234567890abcdef...",
                "description": "OpenRouter API keys start with 'sk-or-'"
            }
        }
        return formats.get(provider, {
            "prefix": "unknown",
            "length": "variable",
            "example": "Check provider documentation",
            "description": "Refer to provider documentation for key format"
        })


# Global service instance
api_key_service = APIKeyService()
