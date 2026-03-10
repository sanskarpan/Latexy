"""
LLM service for resume optimization using OpenAI.
"""

import json
import re
import time
from typing import Any, Dict, List, Optional

import tiktoken
from openai import AsyncOpenAI

from ..core.config import settings
from ..core.logging import get_logger
from ..models.llm_schemas import (
    ATSScore,
    KeywordMatch,
    OptimizationChange,
    OptimizationRequest,
    OptimizationResponse,
)

logger = get_logger(__name__)


class LLMService:
    """Service for LLM-powered resume optimization."""

    def __init__(self):
        """Initialize the LLM service."""
        self.client = None
        if settings.OPENAI_API_KEY:
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.encoding = self._load_tokenizer()

    def _load_tokenizer(self):
        """Load tokenizer with an offline-safe fallback for local/test environments."""
        try:
            return tiktoken.encoding_for_model("gpt-4")
        except Exception as exc:
            logger.warning(f"Failed to load tiktoken model encoding, using fallback tokenizer: {exc}")

            class _FallbackEncoding:
                @staticmethod
                def encode(text: str):
                    # Approximate tokenization fallback (whitespace split).
                    return text.split()

            return _FallbackEncoding()

    def is_available(self) -> bool:
        """Check if LLM service is available."""
        return self.client is not None and bool(settings.OPENAI_API_KEY)

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))

    def extract_keywords_from_job_description(self, job_description: Optional[str]) -> List[str]:
        """Extract relevant keywords from job description."""
        if not job_description:
            return []
        # Simple keyword extraction - can be enhanced with NLP libraries
        text = job_description.lower()

        # Common technical keywords patterns
        patterns = [
            r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b',  # Capitalized terms
            r'\b\w+(?:\.\w+)+\b',  # Technologies like React.js, Node.js
            r'\b\w{2,}\b'  # General words 2+ characters
        ]

        keywords = set()
        for pattern in patterns:
            matches = re.findall(pattern, text)
            keywords.update(matches)

        # Filter out common words
        common_words = {
            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
            'by', 'from', 'up', 'about', 'into', 'through', 'during', 'before',
            'after', 'above', 'below', 'between', 'among', 'this', 'that', 'these',
            'those', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have',
            'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should'
        }

        return [kw for kw in keywords if kw.lower() not in common_words and len(kw) > 2][:50]

    def analyze_keyword_matches(self, latex_content: str, keywords: List[str]) -> List[KeywordMatch]:
        """Analyze which keywords are present in the resume."""
        matches = []
        content_lower = latex_content.lower()

        for keyword in keywords:
            found = keyword.lower() in content_lower
            relevance_score = 0.8 if found else 0.2  # Simple scoring

            matches.append(KeywordMatch(
                keyword=keyword,
                relevance_score=relevance_score,
                found_in_resume=found,
                suggested_context=None if found else f"Consider adding '{keyword}' to relevant sections"
            ))

        return sorted(matches, key=lambda x: x.relevance_score, reverse=True)

    def calculate_ats_score(self, latex_content: str, keyword_matches: List[KeywordMatch]) -> ATSScore:
        """Calculate ATS compatibility score."""
        # Keyword score
        total_keywords = len(keyword_matches)
        found_keywords = sum(1 for match in keyword_matches if match.found_in_resume)
        keyword_score = (found_keywords / total_keywords * 100) if total_keywords > 0 else 0

        # Format score (basic LaTeX structure checks)
        format_checks = [
            r'\\section\*?\{[^}]+\}' in latex_content,  # Has sections
            r'\\begin\{itemize\}' in latex_content or r'\\begin\{enumerate\}' in latex_content,  # Has lists
            r'\\textbf\{[^}]+\}' in latex_content,  # Has bold text
            len(latex_content.split('\n')) > 10,  # Reasonable length
        ]
        format_score = sum(format_checks) / len(format_checks) * 100

        # Content score (basic content quality checks)
        content_checks = [
            len(latex_content) > 500,  # Minimum content length
            'experience' in latex_content.lower(),  # Has experience section
            'education' in latex_content.lower(),  # Has education section
            'skills' in latex_content.lower(),  # Has skills section
        ]
        content_score = sum(content_checks) / len(content_checks) * 100

        # Overall score
        overall_score = (keyword_score * 0.4 + format_score * 0.3 + content_score * 0.3)

        recommendations = []
        if keyword_score < 60:
            recommendations.append("Add more relevant keywords from the job description")
        if format_score < 80:
            recommendations.append("Improve document structure with clear sections and formatting")
        if content_score < 70:
            recommendations.append("Ensure all major resume sections are present and well-developed")

        return ATSScore(
            overall_score=overall_score,
            keyword_score=keyword_score,
            format_score=format_score,
            content_score=content_score,
            recommendations=recommendations
        )

    async def optimize_resume(self, request: OptimizationRequest) -> OptimizationResponse:
        """Optimize resume using LLM."""
        start_time = time.time()

        if not self.is_available():
            return OptimizationResponse(
                success=False,
                original_latex=request.latex_content,
                job_description=request.job_description,
                error_message="OpenAI API key not configured"
            )

        try:
            # Extract keywords from job description
            keywords = self.extract_keywords_from_job_description(request.job_description)
            keyword_matches = self.analyze_keyword_matches(request.latex_content, keywords)

            # Calculate initial ATS score
            self.calculate_ats_score(request.latex_content, keyword_matches)

            # Create optimization prompt
            prompt = self._create_optimization_prompt(
                request.latex_content,
                request.job_description,
                keywords,
                request.optimization_level
            )

            # Count tokens
            self.count_tokens(prompt)

            # Call OpenAI API
            response = await self.client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert resume optimizer specializing in ATS-friendly LaTeX resumes. You help job seekers optimize their resumes for specific job descriptions while maintaining professional formatting."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=settings.OPENAI_MAX_TOKENS,
                temperature=settings.OPENAI_TEMPERATURE,
                response_format={"type": "json_object"}
            )

            # Parse response
            result = json.loads(response.choices[0].message.content)

            # Extract optimized LaTeX
            optimized_latex = result.get('optimized_latex', request.latex_content)
            changes_made = self._parse_changes(result.get('changes', []))

            # Recalculate ATS score for optimized version
            optimized_keyword_matches = self.analyze_keyword_matches(optimized_latex, keywords)
            optimized_ats_score = self.calculate_ats_score(optimized_latex, optimized_keyword_matches)

            # Calculate usage
            total_tokens = response.usage.total_tokens

            optimization_time = time.time() - start_time

            logger.info(f"Resume optimization completed in {optimization_time:.2f}s using {total_tokens} tokens")

            return OptimizationResponse(
                success=True,
                optimized_latex=optimized_latex,
                original_latex=request.latex_content,
                job_description=request.job_description,
                keywords_found=optimized_keyword_matches,
                changes_made=changes_made,
                ats_score=optimized_ats_score,
                optimization_time=optimization_time,
                tokens_used=total_tokens,
                model_used=settings.OPENAI_MODEL,
                warnings=result.get('warnings', [])
            )

        except Exception as e:
            logger.error(f"Error during resume optimization: {e}")
            return OptimizationResponse(
                success=False,
                original_latex=request.latex_content,
                job_description=request.job_description,
                error_message=str(e),
                optimization_time=time.time() - start_time
            )

    def _create_optimization_prompt(
        self,
        latex_content: str,
        job_description: Optional[str],
        keywords: List[str],
        optimization_level: str,
        target_sections: Optional[List[str]] = None,
        custom_instructions: Optional[str] = None,
    ) -> str:
        """Create optimization prompt for LLM using delimiter output format."""

        level_instructions = {
            "conservative": "Make minimal changes, only fixing obvious issues and improving clarity where clearly beneficial.",
            "balanced": "Make moderate improvements to content and structure while maintaining the original style.",
            "aggressive": "Significantly restructure and enhance the resume to maximize ATS compatibility and professional impact."
        }

        if job_description:
            jd_section = f"""JOB DESCRIPTION (optimize specifically for this role):
{job_description}

KEY REQUIREMENTS:
1. Maintain valid LaTeX syntax
2. Keep the professional formatting and structure
3. Incorporate relevant keywords naturally: {', '.join(keywords[:20]) if keywords else 'none extracted'}
4. Improve ATS compatibility for this specific role
5. Enhance content relevance to the job description"""
        else:
            jd_section = """No job description provided — perform general optimization.

KEY REQUIREMENTS:
1. Maintain valid LaTeX syntax
2. Improve clarity, impact, and professional tone of bullet points
3. Strengthen action verbs and quantify achievements where possible
4. Improve ATS compatibility for general job applications
5. Ensure consistent formatting and structure throughout"""

        section_constraint = ""
        if target_sections:
            section_list = ", ".join(target_sections)
            section_constraint = (
                f"\n\nIMPORTANT: Only modify these sections: {section_list}. "
                "Keep ALL other sections byte-for-byte identical to the original."
            )

        user_constraint = ""
        if custom_instructions:
            user_constraint = f"\n\nUser instructions: {custom_instructions}"

        return f"""Please optimize the following LaTeX resume.

OPTIMIZATION LEVEL: {optimization_level}
INSTRUCTIONS: {level_instructions.get(optimization_level, level_instructions['balanced'])}

{jd_section}{section_constraint}{user_constraint}

CURRENT LATEX RESUME:
{latex_content}

IMPORTANT: Ensure the optimized LaTeX is complete and compilable. Do not truncate sections or leave incomplete commands.

Respond in this exact format with no other text outside these markers:
<<<LATEX>>>
[Complete optimized LaTeX document here]
<<<END_LATEX>>>
<<<CHANGES>>>
[JSON array: [{{"section":"...","change_type":"added|modified|removed","reason":"..."}}]]
<<<END_CHANGES>>>
"""

    def _parse_changes(self, changes_data: List[Dict[str, Any]]) -> List[OptimizationChange]:
        """Parse changes from LLM response."""
        changes = []
        for change_data in changes_data:
            try:
                change = OptimizationChange(
                    section=change_data.get('section', 'Unknown'),
                    change_type=change_data.get('change_type', 'modified'),
                    original_text=change_data.get('original_text'),
                    new_text=change_data.get('new_text'),
                    reason=change_data.get('reason', 'No reason provided')
                )
                changes.append(change)
            except Exception as e:
                logger.warning(f"Failed to parse change: {e}")
                continue
        return changes


# Global service instance
llm_service = LLMService()
