from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.academic_cv_service import academic_cv_service

ACADEMIC_CV_LATEX = r"""
\documentclass{article}
\begin{document}
\section{Research Experience}
\textbf{Research Assistant}, Example Lab
\begin{itemize}
  \item Built distributed training pipelines for multimodal models.
  \item Published evaluation tooling used by 4 research groups.
\end{itemize}
\section{Publications}
\begin{itemize}
  \item Doe, J. et al. Neural Systems at ICML 2024.
  \item Doe, J. et al. Retrieval Models at NeurIPS 2023.
\end{itemize}
\section{Teaching Experience}
\begin{itemize}
  \item Taught machine learning to 120 students across 2 semesters.
\end{itemize}
\section{Grants}
\begin{itemize}
  \item NSF Graduate Research Fellowship (\$138,000)
\end{itemize}
\bibliographystyle{plain}
\end{document}
"""

PLAIN_RESUME_LATEX = r"\documentclass{article}\begin{document}\section{Experience}\begin{itemize}\item Built APIs.\end{itemize}\end{document}"


async def _create_resume(
    client: AsyncClient,
    auth_headers: dict,
    latex: str,
    title: str = "Academic CV",
) -> dict:
    resp = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={"title": title, "latex_content": latex},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
class TestAcademicCVService:
    async def test_detect_flags_academic_cv(self) -> None:
        report = academic_cv_service.detect(ACADEMIC_CV_LATEX, document_type="academic_cv")
        assert report.is_academic_cv is True
        assert "publications" in report.detected_sections
        assert "research" in report.detected_sections
        assert report.confidence >= 0.45

    async def test_detect_does_not_flag_simple_resume(self) -> None:
        report = academic_cv_service.detect(PLAIN_RESUME_LATEX, document_type="resume")
        assert report.is_academic_cv is False


@pytest.mark.asyncio
class TestAcademicCVRoutes:
    async def test_report_endpoint_returns_detection(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        resume = await _create_resume(client, auth_headers, ACADEMIC_CV_LATEX)
        resp = await client.get(f"/resumes/{resume['id']}/academic-cv-report", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["is_academic_cv"] is True
        assert "publications" in data["detected_sections"]

    async def test_convert_endpoint_creates_variant_and_submits_job(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        resume = await _create_resume(client, auth_headers, ACADEMIC_CV_LATEX)
        with patch("app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock) as mock_write, patch(
            "app.workers.orchestrator.submit_optimize_and_compile"
        ) as mock_submit:
            resp = await client.post(
                f"/resumes/{resume['id']}/academic-cv-convert",
                headers=auth_headers,
                json={"target_industry": "data_science", "target_role_description": "Applied ML engineer role."},
            )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["report"]["is_academic_cv"] is True
        variant_id = data["variant_resume_id"]

        variant_resp = await client.get(f"/resumes/{variant_id}", headers=auth_headers)
        assert variant_resp.status_code == 200, variant_resp.text
        variant = variant_resp.json()
        assert variant["parent_resume_id"] == resume["id"]
        assert variant["document_type"] == "resume"
        assert "Data Science Resume" in variant["title"]

        mock_write.assert_awaited_once()
        mock_submit.assert_called_once()
        kwargs = mock_submit.call_args.kwargs
        assert kwargs["resume_id"] == variant_id
        assert kwargs["optimization_level"] == "aggressive"
        assert "Target industry: Data Science / Machine Learning." in kwargs["custom_instructions"]

    async def test_convert_endpoint_rejects_non_academic_without_force(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        resume = await _create_resume(client, auth_headers, PLAIN_RESUME_LATEX, title="Plain Resume")
        resp = await client.post(
            f"/resumes/{resume['id']}/academic-cv-convert",
            headers=auth_headers,
            json={"target_industry": "tech"},
        )
        assert resp.status_code == 400

    async def test_convert_endpoint_allows_force_for_non_academic(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        resume = await _create_resume(client, auth_headers, PLAIN_RESUME_LATEX, title="Plain Resume")
        with patch("app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock), patch(
            "app.workers.orchestrator.submit_optimize_and_compile"
        ):
            resp = await client.post(
                f"/resumes/{resume['id']}/academic-cv-convert",
                headers=auth_headers,
                json={"target_industry": "tech", "force": True},
            )
        assert resp.status_code == 201, resp.text
