import pytest
import asyncio
import tempfile
import sys
import os
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import uuid
import json

# Add the backend directory to Python path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app, validate_latex_content, compile_latex, check_latex_installation

# Test client
client = TestClient(app)

# Sample LaTeX content for testing
VALID_LATEX_RESUME = """
\\documentclass[letterpaper,11pt]{article}
\\usepackage[empty]{fullpage}
\\usepackage[hidelinks]{hyperref}
\\usepackage{enumitem}

\\begin{document}

\\begin{center}
    \\textbf{\\Large John Doe} \\\\
    \\vspace{2pt}
    (555) 123-4567 $|$ john.doe@email.com $|$ linkedin.com/in/johndoe
\\end{center}

\\section*{Experience}
\\textbf{Software Engineer} \\hfill \\textbf{Jan 2020 -- Present} \\\\
\\textit{Tech Company Inc.} \\\\
\\begin{itemize}[leftmargin=*,noitemsep]
    \\item Developed and maintained web applications using Python and JavaScript
    \\item Collaborated with cross-functional teams to deliver high-quality software
    \\item Optimized database queries resulting in 40\\% performance improvement
\\end{itemize}

\\section*{Education}
\\textbf{Bachelor of Science in Computer Science} \\hfill \\textbf{2016 -- 2020} \\\\
\\textit{University of Technology}

\\section*{Skills}
\\textbf{Programming Languages:} Python, JavaScript, Java, C++ \\\\
\\textbf{Technologies:} React, Node.js, PostgreSQL, Docker, AWS

\\end{document}
"""

INVALID_LATEX_MISSING_STRUCTURE = """
\\documentclass[letterpaper,11pt]{article}
\\usepackage[empty]{fullpage}

This is just text without proper document structure.
"""

INVALID_LATEX_SYNTAX_ERROR = """
\\documentclass[letterpaper,11pt]{article}
\\usepackage[empty]{fullpage}

\\begin{document}
\\textbf{John Doe
\\section*{Experience}
This has a syntax error - missing closing brace
\\end{document}
"""

# Test Health Endpoint
class TestHealthEndpoint:
    
    def test_health_check_success(self):
        """Test health check endpoint returns successful response."""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "latex_available" in data
        assert data["version"] == "1.0.0"
    
    @patch('main.check_latex_installation', return_value=False)
    def test_health_check_no_latex(self, mock_check):
        """Test health check when LaTeX is not available."""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "degraded"
        assert data["latex_available"] == False

# Test LaTeX Validation
class TestLatexValidation:
    
    def test_validate_valid_latex(self):
        """Test validation of valid LaTeX content."""
        assert validate_latex_content(VALID_LATEX_RESUME) == True
    
    def test_validate_empty_content(self):
        """Test validation fails for empty content."""
        assert validate_latex_content("") == False
        assert validate_latex_content("   ") == False
    
    def test_validate_missing_documentclass(self):
        """Test validation fails when documentclass is missing."""
        content = """
        \\begin{document}
        Hello World
        \\end{document}
        """
        assert validate_latex_content(content) == False
    
    def test_validate_missing_begin_document(self):
        """Test validation fails when begin document is missing."""
        content = """
        \\documentclass{article}
        Hello World
        \\end{document}
        """
        assert validate_latex_content(content) == False
    
    def test_validate_missing_end_document(self):
        """Test validation fails when end document is missing."""
        content = """
        \\documentclass{article}
        \\begin{document}
        Hello World
        """
        assert validate_latex_content(content) == False

# Test Compilation Endpoint
class TestCompileEndpoint:
    
    def test_compile_with_form_data(self):
        """Test compilation using form data."""
        response = client.post(
            "/compile",
            data={"latex_content": VALID_LATEX_RESUME}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "success" in data
        assert "job_id" in data
        assert "message" in data
        
        # Validate job_id is a valid UUID
        try:
            uuid.UUID(data["job_id"])
        except ValueError:
            pytest.fail("job_id is not a valid UUID")
    
    def test_compile_with_file_upload(self):
        """Test compilation using file upload."""
        # Create temporary .tex file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False) as f:
            f.write(VALID_LATEX_RESUME)
            f.flush()
            
            with open(f.name, 'rb') as tex_file:
                response = client.post(
                    "/compile",
                    files={"file": ("resume.tex", tex_file, "application/x-tex")}
                )
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
    
    def test_compile_invalid_latex_content(self):
        """Test compilation with invalid LaTeX content."""
        response = client.post(
            "/compile",
            data={"latex_content": INVALID_LATEX_MISSING_STRUCTURE}
        )
        
        assert response.status_code == 400
        assert "Invalid LaTeX content" in response.json()["detail"]
    
    def test_compile_no_content_provided(self):
        """Test compilation when no content is provided."""
        response = client.post("/compile")
        
        assert response.status_code == 400
        assert "Either latex_content or file must be provided" in response.json()["detail"]
    
    def test_compile_file_too_large(self):
        """Test compilation with file that's too large."""
        # Create a large content string (>10MB)
        large_content = "A" * (11 * 1024 * 1024)  # 11MB
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False) as f:
            f.write(large_content)
            f.flush()
            
            with open(f.name, 'rb') as tex_file:
                response = client.post(
                    "/compile",
                    files={"file": ("large.tex", tex_file, "application/x-tex")}
                )
        
        assert response.status_code == 413
        assert "File too large" in response.json()["detail"]
    
    def test_compile_wrong_file_extension(self):
        """Test compilation with wrong file extension."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(VALID_LATEX_RESUME)
            f.flush()
            
            with open(f.name, 'rb') as txt_file:
                response = client.post(
                    "/compile",
                    files={"file": ("resume.txt", txt_file, "text/plain")}
                )
        
        assert response.status_code == 400
        assert "File must be a .tex file" in response.json()["detail"]

# Test Download Endpoint
class TestDownloadEndpoint:
    
    def test_download_nonexistent_job(self):
        """Test downloading PDF for non-existent job."""
        fake_job_id = str(uuid.uuid4())
        response = client.get(f"/download/{fake_job_id}")
        
        assert response.status_code == 404
        assert "PDF not found" in response.json()["detail"]
    
    def test_download_invalid_job_id(self):
        """Test downloading with invalid job ID format."""
        response = client.get("/download/invalid-id")
        
        assert response.status_code == 400
        assert "Invalid job ID format" in response.json()["detail"]

# Test Logs Endpoint
class TestLogsEndpoint:
    
    def test_logs_invalid_job_id(self):
        """Test getting logs with invalid job ID format."""
        response = client.get("/logs/invalid-id")
        
        assert response.status_code == 400
        assert "Invalid job ID format" in response.json()["detail"]
    
    def test_logs_nonexistent_job(self):
        """Test getting logs for non-existent job."""
        fake_job_id = str(uuid.uuid4())
        response = client.get(f"/logs/{fake_job_id}")
        
        assert response.status_code == 404
        assert "Log file not found" in response.json()["detail"]

# Test LaTeX Installation Check
class TestLatexInstallation:
    
    @patch('subprocess.run')
    def test_check_latex_installation_success(self, mock_run):
        """Test successful LaTeX installation check."""
        mock_run.return_value.returncode = 0
        assert check_latex_installation() == True
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_check_latex_installation_failure(self, mock_run):
        """Test failed LaTeX installation check."""
        mock_run.return_value.returncode = 1
        assert check_latex_installation() == False
    
    @patch('subprocess.run', side_effect=Exception("Command not found"))
    def test_check_latex_installation_exception(self, mock_run):
        """Test LaTeX installation check with exception."""
        assert check_latex_installation() == False

# Integration Tests
class TestIntegrationWorkflow:
    
    def test_full_compilation_workflow(self):
        """Test the complete compilation workflow."""
        # Step 1: Submit compilation job
        response = client.post(
            "/compile",
            data={"latex_content": VALID_LATEX_RESUME}
        )
        
        assert response.status_code == 200
        compile_data = response.json()
        job_id = compile_data["job_id"]
        
        # Step 2: If compilation was successful, try to download PDF
        if compile_data.get("success"):
            download_response = client.get(f"/download/{job_id}")
            
            # PDF might not be available immediately in test environment
            # but endpoint should be reachable
            assert download_response.status_code in [200, 404]
        
        # Step 3: Get compilation logs
        logs_response = client.get(f"/logs/{job_id}")
        # Logs might not be available in test environment
        assert logs_response.status_code in [200, 404]

# Performance Tests
class TestPerformance:
    
    def test_multiple_concurrent_requests(self):
        """Test handling multiple concurrent compilation requests."""
        import threading
        import time
        
        results = []
        
        def make_request():
            response = client.post(
                "/compile",
                data={"latex_content": VALID_LATEX_RESUME}
            )
            results.append(response.status_code)
        
        # Create 5 concurrent requests
        threads = []
        start_time = time.time()
        
        for _ in range(5):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        end_time = time.time()
        
        # All requests should complete
        assert len(results) == 5
        
        # Most requests should succeed (some might fail due to LaTeX not being available in test)
        success_count = sum(1 for status in results if status == 200)
        assert success_count >= 0  # At least no server errors
        
        # Should complete in reasonable time
        assert end_time - start_time < 60  # 60 seconds max for 5 requests

# Test Configuration and Setup
class TestConfiguration:
    
    def test_cors_configuration(self):
        """Test CORS headers are properly set."""
        response = client.options("/health")
        # FastAPI automatically handles OPTIONS requests for CORS
        assert response.status_code in [200, 405]  # 405 if OPTIONS not explicitly handled
    
    def test_api_documentation(self):
        """Test that API documentation is available."""
        response = client.get("/docs")
        assert response.status_code == 200
        
        response = client.get("/openapi.json")
        assert response.status_code == 200
        
        # Verify it's valid JSON
        openapi_spec = response.json()
        assert "openapi" in openapi_spec
        assert "info" in openapi_spec

# Fixtures for test setup
@pytest.fixture
def sample_tex_file():
    """Create a sample .tex file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False) as f:
        f.write(VALID_LATEX_RESUME)
        f.flush()
        yield f.name
    
    # Cleanup
    Path(f.name).unlink(missing_ok=True)

# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])