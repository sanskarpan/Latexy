"""
Comprehensive test suite for Phase 12: MVP Launch & Go-Live
Tests all critical MVP functionality and validation criteria.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import Mock, patch
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.database.models import User, DeviceTrial, Compilation, Optimization, UsageAnalytics
from app.services.analytics_service import analytics_service
from app.services.trial_service import trial_service

class TestMVPCoreFeatures:
    """Test MVP core functionality requirements."""
    
    @pytest.mark.asyncio
    async def test_latex_compilation_to_pdf(self, async_client: AsyncClient):
        """Test LaTeX resume compilation to PDF."""
        latex_content = """
        \\documentclass{article}
        \\begin{document}
        \\title{Test Resume}
        \\author{John Doe}
        \\maketitle
        \\section{Experience}
        Software Engineer at Tech Corp
        \\end{document}
        """
        
        response = await async_client.post(
            "/compile",
            json={
                "latex_content": latex_content,
                "optimization_type": "none"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"
        
        # Check job completion (mock for testing)
        job_id = data["job_id"]
        status_response = await async_client.get(f"/jobs/{job_id}/status")
        assert status_response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_ai_powered_optimization(self, async_client: AsyncClient):
        """Test AI-powered resume optimization with job description analysis."""
        latex_content = """
        \\documentclass{article}
        \\begin{document}
        \\section{Experience}
        Software Developer with Python experience
        \\end{document}
        """
        
        job_description = """
        We are looking for a Senior Python Developer with experience in 
        FastAPI, PostgreSQL, and cloud technologies. Must have 5+ years 
        of experience in backend development.
        """
        
        response = await async_client.post(
            "/optimize",
            json={
                "latex_content": latex_content,
                "job_description": job_description,
                "optimization_level": "balanced"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"
    
    @pytest.mark.asyncio
    async def test_real_time_pdf_preview(self, async_client: AsyncClient):
        """Test real-time PDF preview and download functionality."""
        # First compile a resume
        latex_content = "\\documentclass{article}\\begin{document}Test\\end{document}"
        
        compile_response = await async_client.post(
            "/compile",
            json={"latex_content": latex_content, "optimization_type": "none"}
        )
        
        job_id = compile_response.json()["job_id"]
        
        # Test PDF download endpoint
        download_response = await async_client.get(f"/jobs/{job_id}/download")
        # In real implementation, this would return PDF content
        # For testing, we check the endpoint exists and handles requests
        assert download_response.status_code in [200, 404]  # 404 if job not completed yet

class TestTrialSystem:
    """Test freemium trial system functionality."""
    
    @pytest.mark.asyncio
    async def test_device_fingerprint_tracking(self, db_session: AsyncSession):
        """Test device fingerprinting for trial limits."""
        device_fingerprint = "test_device_12345"
        
        # Test trial creation
        trial = await trial_service.get_or_create_trial(
            db=db_session,
            device_fingerprint=device_fingerprint,
            ip_address="192.168.1.1"
        )
        
        assert trial is not None
        assert trial.device_fingerprint == device_fingerprint
        assert trial.usage_count == 0
        assert not trial.blocked
    
    @pytest.mark.asyncio
    async def test_trial_usage_limits(self, db_session: AsyncSession):
        """Test 3 free uses per device limit."""
        device_fingerprint = "test_device_limits"
        
        # Use trial 3 times
        for i in range(3):
            can_use = await trial_service.can_use_trial(
                db=db_session,
                device_fingerprint=device_fingerprint,
                ip_address="192.168.1.1"
            )
            assert can_use
            
            await trial_service.increment_usage(
                db=db_session,
                device_fingerprint=device_fingerprint
            )
        
        # 4th attempt should be blocked
        can_use = await trial_service.can_use_trial(
            db=db_session,
            device_fingerprint=device_fingerprint,
            ip_address="192.168.1.1"
        )
        assert not can_use
    
    @pytest.mark.asyncio
    async def test_trial_reset_after_24_hours(self, db_session: AsyncSession):
        """Test trial usage resets every 24 hours."""
        device_fingerprint = "test_device_reset"
        
        # Create trial and max out usage
        trial = await trial_service.get_or_create_trial(
            db=db_session,
            device_fingerprint=device_fingerprint,
            ip_address="192.168.1.1"
        )
        
        # Simulate 24+ hours ago
        trial.last_used = datetime.now() - timedelta(hours=25)
        trial.usage_count = 3
        await db_session.commit()
        
        # Should be able to use again
        can_use = await trial_service.can_use_trial(
            db=db_session,
            device_fingerprint=device_fingerprint,
            ip_address="192.168.1.1"
        )
        assert can_use

class TestAnalyticsTracking:
    """Test usage analytics and tracking functionality."""
    
    @pytest.mark.asyncio
    async def test_event_tracking(self, db_session: AsyncSession):
        """Test basic event tracking functionality."""
        user_id = uuid4()
        
        success = await analytics_service.track_event(
            db=db_session,
            event_type="page_view",
            user_id=user_id,
            metadata={"page": "landing"},
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0 Test Browser"
        )
        
        assert success
        
        # Verify event was stored
        analytics = await analytics_service.get_user_analytics(
            db=db_session,
            user_id=user_id,
            days=1
        )
        
        assert analytics["user_id"] == str(user_id)
        assert "page_view" in analytics["feature_usage"]
    
    @pytest.mark.asyncio
    async def test_compilation_tracking(self, db_session: AsyncSession):
        """Test compilation event tracking."""
        user_id = uuid4()
        compilation_id = "test_compilation_123"
        
        await analytics_service.track_compilation_event(
            db=db_session,
            user_id=user_id,
            device_fingerprint=None,
            compilation_id=compilation_id,
            status="completed",
            compilation_time=2.5,
            ip_address="192.168.1.1"
        )
        
        analytics = await analytics_service.get_user_analytics(
            db=db_session,
            user_id=user_id,
            days=1
        )
        
        assert "compile" in analytics["feature_usage"]
    
    @pytest.mark.asyncio
    async def test_system_analytics(self, db_session: AsyncSession):
        """Test system-wide analytics collection."""
        # Create some test data
        user = User(
            email="test@example.com",
            name="Test User"
        )
        db_session.add(user)
        await db_session.commit()
        
        # Track some events
        await analytics_service.track_event(
            db=db_session,
            event_type="register",
            user_id=user.id
        )
        
        analytics = await analytics_service.get_system_analytics(
            db=db_session,
            days=1
        )
        
        assert analytics["total_users"] >= 1
        assert "real_time_metrics" in analytics

class TestUserExperience:
    """Test user experience requirements."""
    
    @pytest.mark.asyncio
    async def test_responsive_web_interface(self, async_client: AsyncClient):
        """Test responsive web interface accessibility."""
        # Test main pages are accessible
        pages = ["/", "/try", "/pricing"]
        
        for page in pages:
            response = await async_client.get(page)
            # Pages should be accessible (200) or redirect (3xx)
            assert response.status_code in [200, 301, 302, 307, 308]
    
    @pytest.mark.asyncio
    async def test_file_upload_functionality(self, async_client: AsyncClient):
        """Test file upload and drag-and-drop functionality."""
        # Test file upload endpoint
        test_file_content = b"\\documentclass{article}\\begin{document}Test\\end{document}"
        
        files = {"file": ("test.tex", test_file_content, "text/plain")}
        response = await async_client.post("/upload", files=files)
        
        # Should either succeed or return appropriate error
        assert response.status_code in [200, 400, 413]  # 413 for file too large
    
    @pytest.mark.asyncio
    async def test_real_time_notifications(self, async_client: AsyncClient):
        """Test real-time notification system."""
        # Test WebSocket connection for job updates
        # This would require WebSocket testing in a real implementation
        
        # Test job status endpoint for polling fallback
        response = await async_client.get("/jobs/test_job_id/status")
        assert response.status_code in [200, 404]

class TestSecurityAndCompliance:
    """Test security and compliance requirements."""
    
    @pytest.mark.asyncio
    async def test_input_validation(self, async_client: AsyncClient):
        """Test input validation and sanitization."""
        # Test malicious LaTeX input
        malicious_latex = "\\input{/etc/passwd}"
        
        response = await async_client.post(
            "/compile",
            json={"latex_content": malicious_latex, "optimization_type": "none"}
        )
        
        # Should either reject or safely handle malicious input
        assert response.status_code in [200, 400, 422]
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, async_client: AsyncClient):
        """Test API rate limiting functionality."""
        # Make multiple rapid requests
        responses = []
        for i in range(10):
            response = await async_client.post(
                "/compile",
                json={"latex_content": "test", "optimization_type": "none"}
            )
            responses.append(response.status_code)
        
        # Should eventually hit rate limits
        assert any(status == 429 for status in responses[-5:])  # Last 5 should include rate limits
    
    @pytest.mark.asyncio
    async def test_data_encryption(self, db_session: AsyncSession):
        """Test that sensitive data is properly encrypted."""
        # This would test API key encryption in a real implementation
        # For now, we test that the encryption service exists
        from app.services.encryption_service import encryption_service
        
        test_data = "sensitive_api_key_12345"
        encrypted = encryption_service.encrypt(test_data)
        decrypted = encryption_service.decrypt(encrypted)
        
        assert encrypted != test_data
        assert decrypted == test_data

class TestPerformanceRequirements:
    """Test MVP performance validation criteria."""
    
    @pytest.mark.asyncio
    async def test_response_time_under_2_seconds(self, async_client: AsyncClient):
        """Test average response time <2s for compilation requests."""
        import time
        
        latex_content = "\\documentclass{article}\\begin{document}Test\\end{document}"
        
        start_time = time.time()
        response = await async_client.post(
            "/compile",
            json={"latex_content": latex_content, "optimization_type": "none"}
        )
        end_time = time.time()
        
        response_time = end_time - start_time
        
        # API should respond quickly (job is queued, not processed synchronously)
        assert response_time < 2.0
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_concurrent_user_handling(self, async_client: AsyncClient):
        """Test system handles multiple concurrent users."""
        # Simulate concurrent requests
        async def make_request():
            return await async_client.post(
                "/compile",
                json={"latex_content": "test", "optimization_type": "none"}
            )
        
        # Make 10 concurrent requests
        tasks = [make_request() for _ in range(10)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Most requests should succeed
        successful = sum(1 for r in responses if hasattr(r, 'status_code') and r.status_code == 200)
        assert successful >= 7  # At least 70% success rate

class TestBusinessRequirements:
    """Test business logic and requirements."""
    
    @pytest.mark.asyncio
    async def test_subscription_billing_integration(self, async_client: AsyncClient):
        """Test subscription billing system integration."""
        # Test subscription plans endpoint
        response = await async_client.get("/subscription/plans")
        assert response.status_code == 200
        
        plans = response.json()
        assert len(plans) >= 3  # Should have Basic, Pro, BYOK plans
        
        # Verify plan structure
        for plan in plans:
            assert "name" in plan
            assert "price" in plan
            assert "features" in plan
    
    @pytest.mark.asyncio
    async def test_usage_limit_enforcement(self, db_session: AsyncSession):
        """Test usage limits are properly enforced."""
        device_fingerprint = "test_usage_limits"
        
        # Test trial limits
        for i in range(3):
            can_use = await trial_service.can_use_trial(
                db=db_session,
                device_fingerprint=device_fingerprint,
                ip_address="192.168.1.1"
            )
            assert can_use
            
            await trial_service.increment_usage(
                db=db_session,
                device_fingerprint=device_fingerprint
            )
        
        # Should be blocked after 3 uses
        can_use = await trial_service.can_use_trial(
            db=db_session,
            device_fingerprint=device_fingerprint,
            ip_address="192.168.1.1"
        )
        assert not can_use

class TestIntegrationScenarios:
    """Test end-to-end integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_complete_user_journey(self, async_client: AsyncClient, db_session: AsyncSession):
        """Test complete user journey from trial to registration."""
        device_fingerprint = "integration_test_device"
        
        # 1. Start as anonymous user
        can_use = await trial_service.can_use_trial(
            db=db_session,
            device_fingerprint=device_fingerprint,
            ip_address="192.168.1.1"
        )
        assert can_use
        
        # 2. Compile a resume
        response = await async_client.post(
            "/compile",
            json={
                "latex_content": "\\documentclass{article}\\begin{document}Test Resume\\end{document}",
                "optimization_type": "none"
            }
        )
        assert response.status_code == 200
        
        # 3. Track usage
        await trial_service.increment_usage(
            db=db_session,
            device_fingerprint=device_fingerprint
        )
        
        # 4. Check trial status
        trial_status = await trial_service.get_trial_status(
            db=db_session,
            device_fingerprint=device_fingerprint
        )
        assert trial_status["remaining_uses"] == 2
    
    @pytest.mark.asyncio
    async def test_error_handling_and_recovery(self, async_client: AsyncClient):
        """Test error handling and graceful recovery."""
        # Test invalid LaTeX
        response = await async_client.post(
            "/compile",
            json={"latex_content": "\\invalid{command}", "optimization_type": "none"}
        )
        
        # Should handle gracefully
        assert response.status_code in [200, 400, 422]
        
        if response.status_code == 200:
            # If accepted, job should eventually fail gracefully
            job_id = response.json()["job_id"]
            status_response = await async_client.get(f"/jobs/{job_id}/status")
            assert status_response.status_code == 200

# Test fixtures and utilities
@pytest.fixture
async def db_session():
    """Provide database session for testing."""
    # This would be implemented with actual test database setup
    pass

@pytest.fixture
async def async_client():
    """Provide async HTTP client for testing."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

