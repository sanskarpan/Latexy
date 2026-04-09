"""
ATS Scoring Service — 3-layer SAAS-grade engine.
Layer 1: Rule-based (accurate LaTeX extraction + expanded corpus)
"""

import asyncio
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger
from .industry_ats_profiles import INDUSTRY_PROFILES, detect_industry, get_profile

logger = get_logger(__name__)


@dataclass
class ATSScoreResult:
    """ATS scoring result data structure."""
    overall_score: float
    category_scores: Dict[str, float]
    recommendations: List[str]
    warnings: List[str]
    strengths: List[str]
    detailed_analysis: Dict[str, Any]
    processing_time: float
    timestamp: str
    multi_dim_scores: Optional[Dict[str, float]] = None
    industry_key: Optional[str] = None
    industry_label: Optional[str] = None


@dataclass
class SectionAnalysis:
    """Analysis result for a resume section."""
    found: bool
    score: float
    content_length: int
    keywords_found: List[str]
    issues: List[str]
    suggestions: List[str]


class ATSScoringService:
    """Service for ATS compatibility scoring."""

    # ------------------------------------------------------------------ #
    #  Class-level corpus constants (testable and expandable)            #
    # ------------------------------------------------------------------ #

    ACTION_VERBS: List[str] = [
        # Leadership
        "led", "managed", "directed", "supervised", "oversaw", "spearheaded",
        "championed", "orchestrated", "mentored", "coached", "guided",
        # Achievement
        "achieved", "delivered", "exceeded", "surpassed", "accomplished",
        "improved", "increased", "reduced", "optimized", "streamlined",
        "generated", "saved", "boosted", "accelerated", "enhanced",
        # Technical
        "developed", "built", "designed", "implemented", "engineered",
        "architected", "created", "deployed", "migrated", "integrated",
        "automated", "refactored", "debugged", "tested", "maintained",
        # Collaboration
        "collaborated", "coordinated", "partnered", "liaised", "facilitated",
        "communicated", "presented", "negotiated", "consulted", "advised",
        # Analysis
        "analyzed", "evaluated", "assessed", "researched", "identified",
        "investigated", "measured", "monitored", "tracked", "audited",
        # Other strong verbs
        "launched", "executed", "established", "initiated", "transformed",
        "modernized", "scaled", "expanded", "drove", "pioneered",
    ]

    TECH_KEYWORDS: List[str] = [
        # Languages
        "python", "javascript", "typescript", "java", "go", "rust",
        "c\\+\\+", "c#", "ruby", "swift", "kotlin", "scala", "r",
        # Frontend
        "react", "vue", "angular", "nextjs", "node", "html", "css",
        # Backend
        "fastapi", "django", "flask", "spring", "express", "graphql",
        # Data/ML
        "sql", "postgresql", "mongodb", "redis", "elasticsearch",
        "tensorflow", "pytorch", "pandas", "numpy", "spark",
        # DevOps/Cloud
        "aws", "gcp", "azure", "docker", "kubernetes", "terraform",
        "ci/cd", "github", "jenkins", "ansible", "linux",
        # Architecture
        "microservices", "api", "rest", "kafka", "rabbitmq",
        # Methodology
        "agile", "scrum", "git", "devops", "tdd",
    ]

    SOFT_SKILLS: List[str] = [
        "leadership", "communication", "teamwork", "collaboration",
        "problem-solving", "analytical", "creative", "adaptable",
        "detail-oriented", "proactive", "initiative", "mentoring",
        "presentation", "negotiation", "strategic",
    ]

    def __init__(self):
        """Initialize the ATS scoring service."""
        self.logger = logger

        # ATS-friendly formatting rules
        self.formatting_rules = {
            "fonts": {
                "preferred": ["Arial", "Helvetica", "Calibri", "Times New Roman", "Georgia"],
                "avoid": ["Comic Sans", "Papyrus", "Impact", "Brush Script"]
            },
            "sections": {
                "required": ["contact", "experience", "education"],
                "recommended": ["summary", "skills", "achievements"],
                "optional": ["certifications", "projects", "publications"]
            },
            "keywords": {
                "action_verbs": self.__class__.ACTION_VERBS,
                "quantifiable_terms": [
                    "percent", "%", "million", "thousand", "increased", "decreased",
                    "improved", "reduced", "saved", "generated", "revenue"
                ]
            }
        }

        # Industry-specific keywords
        self.industry_keywords = {
            "technology": [
                "software", "programming", "development", "coding", "algorithm",
                "database", "API", "cloud", "DevOps", "agile", "scrum",
                "machine learning", "artificial intelligence", "full-stack",
            ],
            "marketing": [
                "campaign", "brand", "digital marketing", "SEO", "analytics",
                "conversion", "engagement", "social media", "content", "ROI",
            ],
            "finance": [
                "financial", "accounting", "budget", "analysis", "investment",
                "risk", "compliance", "audit", "forecasting", "modeling",
            ],
            "healthcare": [
                "patient", "clinical", "medical", "healthcare", "treatment",
                "diagnosis", "therapy", "pharmaceutical", "research",
            ]
        }

        # ATS-unfriendly LaTeX packages
        self.ats_unfriendly_packages = [
            'tikz', 'pgfplots', 'graphicx', 'tabularx', 'longtable',
            'multicol', 'fontawesome', 'fontspec',
        ]

    # ------------------------------------------------------------------ #
    #  Layer 1 — Text extraction (fixed)                                 #
    # ------------------------------------------------------------------ #

    def _extract_text_from_latex(self, latex_content: str) -> str:
        """
        Extract plain text from LaTeX, preserving section names and contact info.

        Order matters: process from innermost to outermost.
        """
        text = latex_content

        # 1. Extract inner text from text-formatting commands
        for cmd in ('textbf', 'textit', 'emph', 'underline', 'texttt',
                    'text', 'mbox', 'hbox', 'textrm', 'textsc', 'textsl'):
            text = re.sub(rf'\\{cmd}\{{([^}}]*)\}}', r'\1', text)

        # 2. Extract section headers — preserve as newline-separated tokens
        text = re.sub(
            r'\\(?:section|subsection|subsubsection|chapter|part)\*?\{([^}]*)\}',
            r'\n\1\n', text
        )

        # 3. Extract href display text (keep second {arg})
        text = re.sub(r'\\href\{[^}]*\}\{([^}]*)\}', r'\1', text)

        # 4. Extract title / author / date content
        text = re.sub(r'\\(?:title|author|date)\{([^}]*)\}', r'\1\n', text)

        # 5. Remove environment markers (begin/end)
        text = re.sub(r'\\(?:begin|end)\{[^}]*\}', '', text)

        # 6. Remove remaining LaTeX commands (strip command + optional args)
        text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})*', '', text)

        # 7. Remove % comments
        text = re.sub(r'%.*$', '', text, flags=re.MULTILINE)

        # 8. Remove leftover braces and backslashes
        text = re.sub(r'[{}\\]', ' ', text)

        # 9. Normalise whitespace
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    # ------------------------------------------------------------------ #
    #  Multi-dimensional scoring methods                                  #
    # ------------------------------------------------------------------ #

    def _score_grammar(self, text: str) -> float:
        """Score grammar quality using rule-based checks."""
        issues = 0
        # Double spaces
        if re.search(r'  +', text):
            issues += 1
        # Double periods
        if re.search(r'\.\.', text):
            issues += 1
        # Inconsistent tense: flag if both present and past action verbs appear non-trivially
        present_verbs = re.findall(
            r'\b(?:manage|develop|lead|build|create|analyze|design|implement|drive|own)\b',
            text, re.IGNORECASE,
        )
        past_verbs = re.findall(
            r'\b(?:managed|developed|led|built|created|analyzed|designed|implemented|drove|owned)\b',
            text, re.IGNORECASE,
        )
        if present_verbs and past_verbs and len(present_verbs) > 1 and len(past_verbs) > 1:
            issues += 1
        return min(100.0, max(0.0, 100.0 - issues * 8))

    def _score_bullet_clarity(self, text: str) -> float:
        """Score clarity and impact of bullet points (text = raw latex_content)."""
        bullet_lines = re.findall(r'\\item\s+(.+?)(?=\\item|\\end\{)', text, re.DOTALL)
        if not bullet_lines:
            return 0.0
        action_verbs_lower = {v.lower() for v in self.ACTION_VERBS}
        passive_patterns = [
            r'\bwas\s+\w+ed\b', r'\bwere\s+\w+ed\b',
            r'\bwas responsible for\b', r'\bwere responsible for\b',
        ]
        scores = []
        for bullet in bullet_lines:
            bullet = bullet.strip()
            if not bullet:
                continue
            score = 0
            # +30 if starts with action verb
            first_word = re.split(r'\W+', bullet)[0].lower() if bullet else ''
            if first_word in action_verbs_lower:
                score += 30
            # +30 if contains a number or percentage
            if re.search(r'\d+%?|\$\d+|\d+[kmb]\b', bullet, re.IGNORECASE):
                score += 30
            # +20 if appropriate length (80-160 chars)
            if 80 <= len(bullet) <= 160:
                score += 20
            # +20 if no passive voice
            if not any(re.search(p, bullet, re.IGNORECASE) for p in passive_patterns):
                score += 20
            scores.append(score)
        return sum(scores) / len(scores) if scores else 0.0

    def _score_section_completeness(self, latex_content: str) -> float:
        """Score how complete the resume sections are."""
        sections = re.findall(r'\\section\{([^}]+)\}', latex_content, re.IGNORECASE)
        sections_lower = [s.lower() for s in sections]
        required = ['experience', 'work', 'education', 'skills', 'contact']
        recommended = ['summary', 'objective', 'projects', 'certifications', 'publications']
        required_found = sum(1 for r in required if any(r in s for s in sections_lower))
        recommended_found = sum(1 for r in recommended if any(r in s for s in sections_lower))
        return (required_found / len(required)) * 70 + (recommended_found / len(recommended)) * 30

    def _score_page_density(self, latex_content: str) -> float:
        """Score content density relative to ideal resume length."""
        text = self._extract_text_from_latex(latex_content)
        word_count = len(text.split())
        if 600 <= word_count <= 900:
            return 95.0
        if 400 <= word_count < 600:
            return 70.0
        if 900 < word_count <= 1100:
            return 80.0
        if word_count < 400:
            return 50.0
        return max(30.0, 80.0 - (word_count - 1100) * 0.05)

    def _score_keyword_density(
        self, text: str, job_description: Optional[str] = None
    ) -> float:
        """Score keyword density; neutral 50 when no job description provided."""
        if not job_description:
            return 50.0
        jd_keywords = self._extract_keywords_from_job_description(job_description)
        if not jd_keywords:
            return 50.0
        matched = sum(
            1 for kw in jd_keywords
            if re.search(rf'\b{re.escape(kw)}\b', text, re.IGNORECASE)
        )
        return min(100.0, (matched / len(jd_keywords)) * 100)

    # ------------------------------------------------------------------ #
    #  Public scoring entry point                                         #
    # ------------------------------------------------------------------ #

    async def score_resume(
        self,
        latex_content: str,
        job_description: Optional[str] = None,
        industry: Optional[str] = None,
        industry_profile_key: str = "generic",
    ) -> ATSScoreResult:
        """Score a resume for ATS compatibility."""
        start_time = asyncio.get_event_loop().time()

        try:
            text_content = self._extract_text_from_latex(latex_content)

            # ── Industry calibration ──────────────────────────────────────
            # Resolve industry key: explicit > auto-detect from JD > generic
            industry_key: str = "generic"
            if industry and industry in INDUSTRY_PROFILES:
                industry_key = industry
            elif industry:
                _legacy_map = {
                    "technology": "tech_saas",
                    "finance": "finance_banking",
                    "healthcare": "healthcare",
                    "consulting": "consulting",
                }
                industry_key = _legacy_map.get(industry.lower(), "generic")
            elif job_description:
                industry_key = detect_industry(job_description)

            profile = get_profile(industry_key)
            is_generic = industry_key == "generic"
            industry_label: Optional[str] = profile["label"] if not is_generic else None

            formatting_score = await self._score_formatting(latex_content)
            # Pass raw latex_content so contact detection can find emails in \href
            structure_score = await self._score_structure(text_content, latex_content)
            content_score = await self._score_content(
                text_content, job_description, industry,
                industry_profile=None if is_generic else profile,
            )
            keyword_score = await self._score_keywords(text_content, job_description, industry)
            readability_score = await self._score_readability(text_content)

            # Multi-dimensional scores (rule-based, fast)
            multi_dim_scores: Dict[str, float] = {
                "grammar": round(self._score_grammar(text_content), 1),
                "bullet_clarity": round(self._score_bullet_clarity(latex_content), 1),
                "section_completeness": round(
                    self._score_section_completeness(latex_content), 1
                ),
                "page_density": round(self._score_page_density(latex_content), 1),
                "keyword_density": round(
                    self._score_keyword_density(text_content, job_description), 1
                ),
            }

            category_scores = {
                "formatting": formatting_score["score"],
                "structure": structure_score["score"],
                "content": content_score["score"],
                "keywords": keyword_score["score"],
                "readability": readability_score["score"],
            }

            # Base weights — adjusted by profile's section_weights multipliers
            base_weights = {
                "formatting": 0.25,
                "structure": 0.20,
                "content": 0.25,
                "keywords": 0.20,
                "readability": 0.10,
            }
            section_weight_map = {
                "experience": "content",   # experience → content category
                "skills": "keywords",      # skills → keywords category
                "education": "structure",  # education → structure category
            }
            profile_section_weights = profile.get("section_weights", {})
            weights = dict(base_weights)
            for prof_key, multiplier in profile_section_weights.items():
                cat = section_weight_map.get(prof_key)
                if cat and cat in weights:
                    weights[cat] = weights[cat] * multiplier

            # Re-normalise so weights still sum to 1.0
            weight_sum = sum(weights.values())
            if weight_sum > 0:
                weights = {k: v / weight_sum for k, v in weights.items()}

            # Apply profile section_weights as multipliers on base category weights
            # Mapping: experience → content, skills → keywords, education → structure
            section_to_category = {
                "experience": "content",
                "skills": "keywords",
                "education": "structure",
            }
            effective_weights = dict(base_weights)
            for section_key, cat_key in section_to_category.items():
                multiplier = profile.get("section_weights", {}).get(section_key, 1.0)
                effective_weights[cat_key] *= multiplier
            # Re-normalise so they sum to 1
            total_w = sum(effective_weights.values())
            weights = {k: v / total_w for k, v in effective_weights.items()}

            overall_score = sum(
                category_scores[cat] * weights[cat] for cat in category_scores
            )

            recommendations: List[str] = []
            warnings: List[str] = []
            strengths: List[str] = []

            for analysis in [formatting_score, structure_score, content_score,
                              keyword_score, readability_score]:
                recommendations.extend(analysis.get("recommendations", []))
                warnings.extend(analysis.get("warnings", []))
                strengths.extend(analysis.get("strengths", []))

            detailed_analysis = {
                "formatting_analysis": formatting_score,
                "structure_analysis": structure_score,
                "content_analysis": content_score,
                "keyword_analysis": keyword_score,
                "readability_analysis": readability_score,
                "section_breakdown": await self._analyze_sections(text_content, latex_content),
                "ats_compatibility": self._check_ats_compatibility(latex_content),
                "improvement_priority": self._prioritize_improvements(category_scores),
                "industry_calibration": {
                    "industry_key": industry_key,
                    "industry_label": industry_label,
                    "profile_applied": industry_key != "generic",
                },
            }

            processing_time = asyncio.get_event_loop().time() - start_time

            result = ATSScoreResult(
                overall_score=round(overall_score, 1),
                category_scores=category_scores,
                recommendations=recommendations[:10],
                warnings=warnings[:5],
                strengths=strengths[:5],
                detailed_analysis=detailed_analysis,
                processing_time=processing_time,
                timestamp=datetime.utcnow().isoformat(),
                multi_dim_scores=multi_dim_scores,
                industry_key=industry_key,
                industry_label=industry_label,
            )

            self.logger.info(
                f"ATS scoring completed: {overall_score:.1f}/100 "
                f"(industry={industry_key}) in {processing_time:.2f}s"
            )
            return result

        except Exception as e:
            self.logger.error(f"ATS scoring failed: {e}")
            processing_time = asyncio.get_event_loop().time() - start_time
            return ATSScoreResult(
                overall_score=0.0,
                category_scores={},
                recommendations=[f"Error during scoring: {str(e)}"],
                warnings=["Scoring failed - please check resume format"],
                strengths=[],
                detailed_analysis={"error": str(e)},
                processing_time=processing_time,
                timestamp=datetime.utcnow().isoformat(),
            )

    # ------------------------------------------------------------------ #
    #  Formatting score                                                   #
    # ------------------------------------------------------------------ #

    async def _score_formatting(self, latex_content: str) -> Dict[str, Any]:
        """Score formatting aspects of the resume."""
        score = 100.0
        recommendations: List[str] = []
        warnings: List[str] = []
        strengths: List[str] = []

        # ATS-unfriendly packages: each -8, capped at -40
        deduction = 0
        flagged = []
        for package in self.ats_unfriendly_packages:
            if re.search(rf'\\usepackage(?:\[[^\]]*\])?\{{{re.escape(package)}\}}', latex_content) \
               or package in latex_content:
                deduction += 8
                flagged.append(package)
                warnings.append(f"Package '{package}' may cause ATS parsing issues")
                recommendations.append(f"Consider removing or replacing '{package}' package")
        score -= min(deduction, 40)

        if '\\documentclass' in latex_content:
            strengths.append("Proper LaTeX document structure")
        else:
            score -= 20
            warnings.append("Missing document class declaration")

        font_commands = re.findall(r'\\usepackage\{([^}]*font[^}]*)\}', latex_content)
        for font in font_commands:
            if any(bad in font.lower() for bad in ['comic', 'script', 'decorative']):
                score -= 15
                warnings.append(f"Font package '{font}' may not be ATS-friendly")
            else:
                strengths.append("Uses standard font packages")

        complex_patterns = [
            r'\\begin\{table\}', r'\\begin\{figure\}', r'\\begin\{minipage\}',
            r'\\multicolumn', r'\\multirow', r'\\includegraphics',
        ]
        for pattern in complex_patterns:
            if re.search(pattern, latex_content):
                score -= 5
                recommendations.append("Simplify complex formatting for better ATS compatibility")
                break

        if '\\section' in latex_content:
            strengths.append("Uses clear section headers")
        if '\\item' in latex_content:
            strengths.append("Uses bullet points effectively")

        return {
            "score": max(0, score),
            "recommendations": recommendations,
            "warnings": warnings,
            "strengths": strengths,
            "details": {
                "unfriendly_packages_found": len(flagged),
                "has_proper_structure": '\\documentclass' in latex_content,
                "uses_sections": '\\section' in latex_content,
            },
        }

    # ------------------------------------------------------------------ #
    #  Structure score (fixed contact detection)                         #
    # ------------------------------------------------------------------ #

    async def _score_structure(
        self, text_content: str, latex_content: str = ""
    ) -> Dict[str, Any]:
        """Score the structural organisation of the resume."""
        score = 100.0
        recommendations: List[str] = []
        warnings: List[str] = []
        strengths: List[str] = []

        # Contact detection — use raw LaTeX so emails inside \href are found
        raw_to_check = latex_content if latex_content else text_content
        has_email = bool(re.search(
            r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', raw_to_check
        ))
        has_phone = bool(re.search(
            r'[\+\(]?[1-9][0-9 .\-\(\)]{8,}[0-9]', raw_to_check
        ))
        contact_found = has_email or has_phone

        sections_found: Dict[str, bool] = {}

        if contact_found:
            sections_found["contact"] = True
            strengths.append("Contains contact section")
        else:
            sections_found["contact"] = False
            score -= 25
            warnings.append("Missing contact section")
            recommendations.append("Add a clear contact section with email and phone")

        # Experience section
        exp_patterns = [r'experience', r'work', r'employment', r'career']
        exp_found = any(re.search(p, text_content, re.IGNORECASE) for p in exp_patterns)
        sections_found["experience"] = exp_found
        if exp_found:
            strengths.append("Contains experience section")
        else:
            score -= 25
            warnings.append("Missing experience section")
            recommendations.append("Add a clear experience section")

        # Education section
        edu_patterns = [r'education', r'degree', r'university', r'college', r'school']
        edu_found = any(re.search(p, text_content, re.IGNORECASE) for p in edu_patterns)
        sections_found["education"] = edu_found
        if edu_found:
            strengths.append("Contains education section")
        else:
            score -= 25
            warnings.append("Missing education section")
            recommendations.append("Add a clear education section")

        # Recommended sections (softer penalty)
        recommended_sections = {
            "summary": [r'summary', r'objective', r'profile'],
            "skills": [r'skills', r'competencies', r'technologies'],
            "achievements": [r'achievements', r'accomplishments', r'awards'],
        }
        for section, patterns in recommended_sections.items():
            found = any(re.search(p, text_content, re.IGNORECASE) for p in patterns)
            if found:
                strengths.append(f"Includes {section} section")
            else:
                score -= 5
                recommendations.append(f"Consider adding a {section} section")

        # Word count check
        word_count = len(text_content.split())
        if word_count < 200:
            score -= 30
            warnings.append("Resume content is too brief (under 200 words)")
            recommendations.append("Expand resume content to 300-600 words")
        elif 500 <= word_count <= 900:
            strengths.append("Appropriate content length")
        elif word_count > 900:
            score -= 10
            recommendations.append("Consider condensing resume content (over 900 words)")

        return {
            "score": max(0, score),
            "recommendations": recommendations,
            "warnings": warnings,
            "strengths": strengths,
            "details": {
                "sections_found": sections_found,
                "word_count": word_count,
                "structure_score": len([s for s in sections_found.values() if s]) / max(len(sections_found), 1) * 100,
            },
        }

    # ------------------------------------------------------------------ #
    #  Content score                                                      #
    # ------------------------------------------------------------------ #

    async def _score_content(
        self,
        text_content: str,
        job_description: Optional[str] = None,
        industry: Optional[str] = None,
        industry_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Score the content quality and relevance."""
        score = 100.0
        recommendations: List[str] = []
        warnings: List[str] = []
        strengths: List[str] = []

        # Action verbs check (against expanded corpus)
        action_verbs_found = [
            v for v in self.ACTION_VERBS
            if re.search(rf'\b{re.escape(v)}\b', text_content, re.IGNORECASE)
        ]
        action_verb_ratio = len(action_verbs_found) / len(self.ACTION_VERBS)

        if action_verb_ratio > 0.15:
            strengths.append("Uses strong action verbs effectively")
        elif action_verb_ratio > 0.05:
            recommendations.append("Include more action verbs to strengthen impact")
        else:
            score -= 15
            warnings.append("Lacks strong action verbs")
            recommendations.append("Add action verbs like 'achieved', 'managed', 'developed'")

        # Quantifiable achievements
        quantifiable_patterns = [
            r'\d+%', r'\$\d+', r'\d+\s*(million|thousand|k)',
            r'increased.*\d+', r'reduced.*\d+', r'improved.*\d+',
        ]
        quantifiable_found = sum(
            1 for p in quantifiable_patterns
            if re.search(p, text_content, re.IGNORECASE)
        )

        if quantifiable_found >= 3:
            strengths.append("Includes quantifiable achievements")
        elif quantifiable_found >= 1:
            recommendations.append("Add more quantifiable achievements")
        else:
            score -= 20
            warnings.append("Lacks quantifiable achievements")
            recommendations.append("Include specific numbers, percentages, and metrics")

        # Industry keyword matching — use weighted profile if available, else legacy flat list
        keywords_found: List[str] = []
        match_ratio: float = 0.0

        if industry_profile and industry_profile.get("keywords"):
            # Weighted profile keyword scoring — single scan per keyword
            profile_keywords = industry_profile["keywords"]
            total_weight = sum(profile_keywords.values())
            keywords_found = [
                kw for kw in profile_keywords
                if re.search(rf'\b{re.escape(kw)}\b', text_content, re.IGNORECASE)
            ]
            weighted_score = sum(profile_keywords[kw] for kw in keywords_found)
            keyword_ratio = weighted_score / max(total_weight, 1)
            profile_label = industry_profile.get("label", industry or "industry")
            if keyword_ratio > 0.25:
                strengths.append(f"Strong {profile_label} keyword presence")
            elif keyword_ratio > 0.12:
                recommendations.append(f"Include more {profile_label} keywords")
            else:
                score -= 10
                recommendations.append(f"Add relevant {profile_label} keywords")
        elif industry and industry in self.industry_keywords:
            industry_keywords = self.industry_keywords[industry]
            keywords_found = [
                kw for kw in industry_keywords
                if re.search(rf'\b{re.escape(kw)}\b', text_content, re.IGNORECASE)
            ]
            keyword_ratio = len(keywords_found) / max(len(industry_keywords), 1)
            if keyword_ratio > 0.4:
                strengths.append(f"Strong {industry} industry keyword presence")
            elif keyword_ratio > 0.2:
                recommendations.append(f"Include more {industry} industry keywords")
            else:
                score -= 10
                recommendations.append(f"Add relevant {industry} industry keywords")

        # JD keyword matching
        if job_description:
            jd_keywords = self._extract_keywords_from_job_description(job_description)
            matching_keywords = [
                kw for kw in jd_keywords
                if re.search(rf'\b{re.escape(kw)}\b', text_content, re.IGNORECASE)
            ]
            match_ratio = len(matching_keywords) / max(len(jd_keywords), 1)
            if match_ratio > 0.6:
                strengths.append("Excellent job description keyword alignment")
            elif match_ratio > 0.3:
                recommendations.append("Improve keyword alignment with job description")
            else:
                score -= 15
                warnings.append("Poor keyword alignment with job description")
                recommendations.append("Include more keywords from the job description")

        return {
            "score": max(0, score),
            "recommendations": recommendations,
            "warnings": warnings,
            "strengths": strengths,
            "details": {
                "action_verbs_found": action_verbs_found[:10],
                "action_verb_ratio": action_verb_ratio,
                "quantifiable_achievements": quantifiable_found,
                "industry_keywords_found": keywords_found,
                "job_match_ratio": match_ratio,
            },
        }

    # ------------------------------------------------------------------ #
    #  Keyword score (expanded corpus)                                   #
    # ------------------------------------------------------------------ #

    async def _score_keywords(
        self,
        text_content: str,
        job_description: Optional[str] = None,
        industry: Optional[str] = None,
        industry_key: str = "generic",
    ) -> Dict[str, Any]:
        """Score keyword optimisation and density, with industry-profile weighting."""
        score = 100.0
        recommendations: List[str] = []
        warnings: List[str] = []
        strengths: List[str] = []

        words = text_content.lower().split()
        word_count = len(words)

        if word_count == 0:
            return {
                "score": 0,
                "recommendations": ["Add content to analyse keywords"],
                "warnings": ["No content found"],
                "strengths": [],
                "details": {},
            }

        # Keyword stuffing detection
        word_frequency: Dict[str, int] = {}
        for word in words:
            if len(word) > 3:
                word_frequency[word] = word_frequency.get(word, 0) + 1

        stuffed_keywords = [
            word for word, count in word_frequency.items()
            if count / word_count > 0.05 and count > 3
        ]
        if stuffed_keywords:
            score -= 20
            warnings.append("Potential keyword stuffing detected")
            recommendations.append("Reduce repetition of overused keywords")
        else:
            strengths.append("Natural keyword distribution")

        # ── Industry-profile keyword bonus ───────────────────────────────
        profile = get_profile(industry_key)
        profile_keywords: Dict[str, float] = profile.get("keywords", {})
        calibrated_hit_score: float = 0.0
        calibrated_total_weight: float = 0.0
        calibrated_hits: List[str] = []

        if profile_keywords:
            for kw, weight in profile_keywords.items():
                calibrated_total_weight += weight
                if re.search(rf'\b{re.escape(kw)}\b', text_content, re.IGNORECASE):
                    calibrated_hit_score += weight
                    calibrated_hits.append(kw)

            hit_ratio = calibrated_hit_score / calibrated_total_weight if calibrated_total_weight else 0
            if hit_ratio >= 0.4:
                strengths.append(f"Strong {profile['label']} keyword presence")
                score = min(100.0, score + 5)
            elif hit_ratio >= 0.2:
                recommendations.append(
                    f"Include more {profile['label']}-specific keywords to improve calibration"
                )
            else:
                score -= 8
                recommendations.append(
                    f"Resume lacks key {profile['label']} terminology (e.g. "
                    + ", ".join(list(profile_keywords.keys())[:4]) + ")"
                )

        # Tech keywords (expanded corpus)
        tech_found = [
            kw for kw in self.TECH_KEYWORDS
            if re.search(rf'\b{kw}\b', text_content, re.IGNORECASE)
        ]
        if len(tech_found) >= 8:
            strengths.append("Rich technical keyword presence")
        elif len(tech_found) >= 4:
            recommendations.append("Consider adding more relevant technical keywords")
        else:
            score -= 10
            recommendations.append("Include relevant technical skills and keywords")

        # Soft skills (expanded corpus)
        soft_skills_found = [
            skill for skill in self.SOFT_SKILLS
            if re.search(rf'\b{re.escape(skill)}\b', text_content, re.IGNORECASE)
        ]
        if len(soft_skills_found) >= 4:
            strengths.append("Good soft skills representation")
        else:
            recommendations.append("Include relevant soft skills")

        return {
            "score": max(0, score),
            "recommendations": recommendations,
            "warnings": warnings,
            "strengths": strengths,
            "details": {
                "word_count": word_count,
                "unique_words": len(word_frequency),
                "stuffed_keywords": stuffed_keywords,
                "tech_keywords_found": tech_found,
                "soft_skills_found": soft_skills_found,
                "keyword_density": len(set(words)) / word_count if word_count > 0 else 0,
                "calibrated_industry": industry_key,
                "calibrated_hits": calibrated_hits,
            },
        }

    # ------------------------------------------------------------------ #
    #  Readability score                                                  #
    # ------------------------------------------------------------------ #

    async def _score_readability(self, text_content: str) -> Dict[str, Any]:
        """Score readability and clarity."""
        score = 100.0
        recommendations: List[str] = []
        warnings: List[str] = []
        strengths: List[str] = []

        if not text_content.strip():
            return {
                "score": 0,
                "recommendations": ["Add content to analyse readability"],
                "warnings": ["No content found"],
                "strengths": [],
                "details": {},
            }

        sentences = re.split(r'[.!?]+', text_content)
        sentences = [s.strip() for s in sentences if s.strip()]
        words = text_content.split()

        avg_sentence_length = len(words) / max(len(sentences), 1)

        if avg_sentence_length > 25:
            score -= 15
            warnings.append("Sentences are too long")
            recommendations.append("Use shorter, more concise sentences")
        elif avg_sentence_length < 8:
            score -= 5
            recommendations.append("Consider varying sentence length")
        else:
            strengths.append("Appropriate sentence length")

        passive_indicators = ['was', 'were', 'been', 'being']
        passive_count = sum(1 for w in words if w.lower() in passive_indicators)
        passive_ratio = passive_count / max(len(words), 1)

        if passive_ratio > 0.1:
            score -= 10
            recommendations.append("Reduce passive voice usage")
        else:
            strengths.append("Uses active voice effectively")

        filler_words = ['very', 'really', 'quite', 'rather', 'somewhat']
        filler_count = sum(1 for w in words if w.lower() in filler_words)
        if filler_count > len(words) * 0.02:
            score -= 5
            recommendations.append("Remove unnecessary filler words")

        informal_words = ['awesome', 'cool', 'stuff', 'things', 'guys']
        informal_count = sum(1 for w in words if w.lower() in informal_words)
        if informal_count > 0:
            score -= 10
            warnings.append("Contains informal language")
            recommendations.append("Use professional language throughout")
        else:
            strengths.append("Maintains professional tone")

        return {
            "score": max(0, score),
            "recommendations": recommendations,
            "warnings": warnings,
            "strengths": strengths,
            "details": {
                "sentence_count": len(sentences),
                "avg_sentence_length": avg_sentence_length,
                "passive_ratio": passive_ratio,
                "filler_word_count": filler_count,
                "informal_word_count": informal_count,
            },
        }

    # ------------------------------------------------------------------ #
    #  Section analysis                                                   #
    # ------------------------------------------------------------------ #

    async def _analyze_sections(
        self, text_content: str, latex_content: str = ""
    ) -> Dict[str, Any]:
        """Analyse individual resume sections."""
        raw = latex_content if latex_content else text_content

        # Contact
        has_email = bool(re.search(
            r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', raw
        ))
        has_phone = bool(re.search(r'[\+\(]?[1-9][0-9 .\-\(\)]{8,}[0-9]', raw))
        contact_found = has_email or has_phone

        exp_patterns = [r'experience', r'work', r'employment', r'career']
        exp_found = any(re.search(p, text_content, re.IGNORECASE) for p in exp_patterns)

        edu_patterns = [r'education', r'degree', r'university', r'college']
        edu_found = any(re.search(p, text_content, re.IGNORECASE) for p in edu_patterns)

        return {
            "contact": asdict(SectionAnalysis(
                found=contact_found,
                score=100 if contact_found else 0,
                content_length=len(re.findall(r'[@\d\-\.]', raw)),
                keywords_found=[p for p in ['email', 'phone'] if re.search(p, text_content, re.IGNORECASE)],
                issues=[] if contact_found else ["Missing contact information"],
                suggestions=[] if contact_found else ["Add email and phone number"],
            )),
            "experience": asdict(SectionAnalysis(
                found=exp_found,
                score=100 if exp_found else 0,
                content_length=len(text_content.split()) // 3,
                keywords_found=[p for p in exp_patterns if re.search(p, text_content, re.IGNORECASE)],
                issues=[] if exp_found else ["Missing work experience"],
                suggestions=[] if exp_found else ["Add work experience section"],
            )),
            "education": asdict(SectionAnalysis(
                found=edu_found,
                score=100 if edu_found else 0,
                content_length=len(text_content.split()) // 4,
                keywords_found=[p for p in edu_patterns if re.search(p, text_content, re.IGNORECASE)],
                issues=[] if edu_found else ["Missing education information"],
                suggestions=[] if edu_found else ["Add education section"],
            )),
        }

    # ------------------------------------------------------------------ #
    #  ATS compatibility check                                           #
    # ------------------------------------------------------------------ #

    def _check_ats_compatibility(self, latex_content: str) -> Dict[str, Any]:
        """Check for ATS compatibility issues."""
        issues: List[str] = []
        compatibility_score = 100

        problematic_elements = {
            'tables': r'\\begin\{table\}|\\begin\{tabular\}',
            'graphics': r'\\includegraphics|\\begin\{figure\}',
            'complex_formatting': r'\\multicolumn|\\multirow',
            'text_boxes': r'\\fbox|\\framebox',
            'headers_footers': r'\\fancyhdr|\\pagestyle',
        }

        for element, pattern in problematic_elements.items():
            if re.search(pattern, latex_content):
                issues.append(f"Contains {element.replace('_', ' ')} which may cause ATS issues")
                compatibility_score -= 15

        return {
            "compatibility_score": max(0, compatibility_score),
            "issues": issues,
            "ats_friendly": compatibility_score >= 80,
        }

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _prioritize_improvements(
        self, category_scores: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """Prioritise improvements based on category scores."""
        improvements = []
        for category, score in category_scores.items():
            if score < 70:
                priority = "high" if score < 50 else "medium"
                improvements.append({
                    "category": category,
                    "current_score": score,
                    "priority": priority,
                    "potential_impact": 100 - score,
                })
        improvements.sort(key=lambda x: x["potential_impact"], reverse=True)
        return improvements

    def _extract_keywords_from_job_description(self, job_description: str) -> List[str]:
        """Extract relevant keywords from job description."""
        words = re.findall(r'\b[a-zA-Z]{3,}\b', job_description.lower())
        stop_words = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
            'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his',
            'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'who', 'did',
            'she', 'use', 'way', 'many', 'will', 'with', 'that', 'this', 'from',
            'have', 'they', 'been', 'work', 'your', 'more', 'also', 'able', 'each',
        }
        keywords = [w for w in words if w not in stop_words and len(w) > 3]
        return list(dict.fromkeys(keywords))[:30]


# Global service instance
ats_scoring_service = ATSScoringService()
