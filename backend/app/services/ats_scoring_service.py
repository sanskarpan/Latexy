"""
ATS Scoring Service for Phase 9.
Comprehensive ATS compatibility scoring system.
"""

import re
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import asyncio

from ..core.logging import get_logger
from ..core.config import settings

logger = get_logger(__name__)


@dataclass
class ATSScoreResult:
    """ATS scoring result data structure."""
    overall_score: float  # 0-100
    category_scores: Dict[str, float]
    recommendations: List[str]
    warnings: List[str]
    strengths: List[str]
    detailed_analysis: Dict[str, Any]
    processing_time: float
    timestamp: str


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
                "action_verbs": [
                    "achieved", "managed", "developed", "created", "implemented",
                    "led", "improved", "increased", "reduced", "optimized",
                    "designed", "built", "launched", "delivered", "executed"
                ],
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
                "database", "API", "cloud", "DevOps", "agile", "scrum"
            ],
            "marketing": [
                "campaign", "brand", "digital marketing", "SEO", "analytics",
                "conversion", "engagement", "social media", "content"
            ],
            "finance": [
                "financial", "accounting", "budget", "analysis", "investment",
                "risk", "compliance", "audit", "forecasting", "modeling"
            ],
            "healthcare": [
                "patient", "clinical", "medical", "healthcare", "treatment",
                "diagnosis", "therapy", "pharmaceutical", "research"
            ]
        }
        
        # Common ATS parsing issues
        self.ats_issues = {
            "formatting": [
                "tables", "text boxes", "headers/footers", "columns",
                "graphics", "images", "special characters"
            ],
            "file_format": ["pdf_with_images", "docx_complex", "html", "rtf"],
            "fonts": ["non_standard", "decorative", "script"],
            "structure": ["missing_sections", "poor_hierarchy", "inconsistent_formatting"]
        }
    
    async def score_resume(
        self, 
        latex_content: str, 
        job_description: Optional[str] = None,
        industry: Optional[str] = None
    ) -> ATSScoreResult:
        """
        Score a resume for ATS compatibility.
        
        Args:
            latex_content: LaTeX resume content
            job_description: Optional job description for keyword matching
            industry: Optional industry for specialized scoring
            
        Returns:
            ATSScoreResult with comprehensive scoring data
        """
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Extract text content from LaTeX
            text_content = self._extract_text_from_latex(latex_content)
            
            # Perform comprehensive analysis
            formatting_score = await self._score_formatting(latex_content)
            structure_score = await self._score_structure(text_content)
            content_score = await self._score_content(text_content, job_description, industry)
            keyword_score = await self._score_keywords(text_content, job_description, industry)
            readability_score = await self._score_readability(text_content)
            
            # Calculate category scores
            category_scores = {
                "formatting": formatting_score["score"],
                "structure": structure_score["score"],
                "content": content_score["score"],
                "keywords": keyword_score["score"],
                "readability": readability_score["score"]
            }
            
            # Calculate overall score (weighted average)
            weights = {
                "formatting": 0.25,
                "structure": 0.20,
                "content": 0.25,
                "keywords": 0.20,
                "readability": 0.10
            }
            
            overall_score = sum(
                category_scores[category] * weights[category]
                for category in category_scores
            )
            
            # Collect recommendations, warnings, and strengths
            recommendations = []
            warnings = []
            strengths = []
            
            for analysis in [formatting_score, structure_score, content_score, keyword_score, readability_score]:
                recommendations.extend(analysis.get("recommendations", []))
                warnings.extend(analysis.get("warnings", []))
                strengths.extend(analysis.get("strengths", []))
            
            # Create detailed analysis
            detailed_analysis = {
                "formatting_analysis": formatting_score,
                "structure_analysis": structure_score,
                "content_analysis": content_score,
                "keyword_analysis": keyword_score,
                "readability_analysis": readability_score,
                "section_breakdown": await self._analyze_sections(text_content),
                "ats_compatibility": self._check_ats_compatibility(latex_content),
                "improvement_priority": self._prioritize_improvements(category_scores)
            }
            
            processing_time = asyncio.get_event_loop().time() - start_time
            
            result = ATSScoreResult(
                overall_score=round(overall_score, 1),
                category_scores=category_scores,
                recommendations=recommendations[:10],  # Top 10 recommendations
                warnings=warnings[:5],  # Top 5 warnings
                strengths=strengths[:5],  # Top 5 strengths
                detailed_analysis=detailed_analysis,
                processing_time=processing_time,
                timestamp=datetime.utcnow().isoformat()
            )
            
            self.logger.info(f"ATS scoring completed: {overall_score:.1f}/100 in {processing_time:.2f}s")
            return result
            
        except Exception as e:
            self.logger.error(f"ATS scoring failed: {e}")
            # Return a default low score with error information
            processing_time = asyncio.get_event_loop().time() - start_time
            return ATSScoreResult(
                overall_score=0.0,
                category_scores={},
                recommendations=[f"Error during scoring: {str(e)}"],
                warnings=["Scoring failed - please check resume format"],
                strengths=[],
                detailed_analysis={"error": str(e)},
                processing_time=processing_time,
                timestamp=datetime.utcnow().isoformat()
            )
    
    def _extract_text_from_latex(self, latex_content: str) -> str:
        """Extract plain text from LaTeX content."""
        # Remove LaTeX commands and environments
        text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})*', '', latex_content)
        
        # Remove comments
        text = re.sub(r'%.*$', '', text, flags=re.MULTILINE)
        
        # Remove special characters and normalize whitespace
        text = re.sub(r'[{}\\]', '', text)
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    async def _score_formatting(self, latex_content: str) -> Dict[str, Any]:
        """Score formatting aspects of the resume."""
        score = 100.0
        recommendations = []
        warnings = []
        strengths = []
        
        # Check for ATS-unfriendly LaTeX packages
        unfriendly_packages = [
            'tikz', 'pgfplots', 'graphicx', 'includegraphics',
            'tabularx', 'longtable', 'multicol'
        ]
        
        for package in unfriendly_packages:
            if package in latex_content:
                score -= 10
                warnings.append(f"Package '{package}' may cause ATS parsing issues")
                recommendations.append(f"Consider removing or replacing '{package}' package")
        
        # Check for proper document structure
        if '\\documentclass' in latex_content:
            strengths.append("Proper LaTeX document structure")
        else:
            score -= 20
            warnings.append("Missing document class declaration")
        
        # Check for standard fonts
        font_commands = re.findall(r'\\usepackage\{([^}]*font[^}]*)\}', latex_content)
        if font_commands:
            for font in font_commands:
                if any(bad_font in font.lower() for bad_font in ['comic', 'script', 'decorative']):
                    score -= 15
                    warnings.append(f"Font package '{font}' may not be ATS-friendly")
                else:
                    strengths.append("Uses standard font packages")
        
        # Check for complex formatting
        complex_patterns = [
            r'\\begin\{table\}', r'\\begin\{figure\}', r'\\begin\{minipage\}',
            r'\\multicolumn', r'\\multirow', r'\\includegraphics'
        ]
        
        for pattern in complex_patterns:
            if re.search(pattern, latex_content):
                score -= 5
                recommendations.append("Simplify complex formatting for better ATS compatibility")
                break
        
        # Positive checks
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
                "unfriendly_packages_found": len([p for p in unfriendly_packages if p in latex_content]),
                "has_proper_structure": '\\documentclass' in latex_content,
                "uses_sections": '\\section' in latex_content
            }
        }
    
    async def _score_structure(self, text_content: str) -> Dict[str, Any]:
        """Score the structural organization of the resume."""
        score = 100.0
        recommendations = []
        warnings = []
        strengths = []
        
        # Check for required sections
        required_sections = {
            "contact": [r'email', r'phone', r'@', r'\d{3}[-.]?\d{3}[-.]?\d{4}'],
            "experience": [r'experience', r'work', r'employment', r'career'],
            "education": [r'education', r'degree', r'university', r'college', r'school']
        }
        
        sections_found = {}
        for section, patterns in required_sections.items():
            found = any(re.search(pattern, text_content, re.IGNORECASE) for pattern in patterns)
            sections_found[section] = found
            
            if found:
                strengths.append(f"Contains {section} section")
            else:
                score -= 25
                warnings.append(f"Missing {section} section")
                recommendations.append(f"Add a clear {section} section")
        
        # Check for recommended sections
        recommended_sections = {
            "summary": [r'summary', r'objective', r'profile'],
            "skills": [r'skills', r'competencies', r'technologies'],
            "achievements": [r'achievements', r'accomplishments', r'awards']
        }
        
        for section, patterns in recommended_sections.items():
            found = any(re.search(pattern, text_content, re.IGNORECASE) for pattern in patterns)
            if found:
                strengths.append(f"Includes {section} section")
            else:
                score -= 5
                recommendations.append(f"Consider adding a {section} section")
        
        # Check content length
        word_count = len(text_content.split())
        if word_count < 200:
            score -= 20
            warnings.append("Resume content is too brief")
            recommendations.append("Expand resume content to 300-600 words")
        elif word_count > 800:
            score -= 10
            recommendations.append("Consider condensing resume content")
        else:
            strengths.append("Appropriate content length")
        
        return {
            "score": max(0, score),
            "recommendations": recommendations,
            "warnings": warnings,
            "strengths": strengths,
            "details": {
                "sections_found": sections_found,
                "word_count": word_count,
                "structure_score": len([s for s in sections_found.values() if s]) / len(sections_found) * 100
            }
        }
    
    async def _score_content(
        self, 
        text_content: str, 
        job_description: Optional[str] = None,
        industry: Optional[str] = None
    ) -> Dict[str, Any]:
        """Score the content quality and relevance."""
        score = 100.0
        recommendations = []
        warnings = []
        strengths = []
        
        # Check for action verbs
        action_verbs_found = []
        for verb in self.formatting_rules["keywords"]["action_verbs"]:
            if re.search(rf'\b{verb}\b', text_content, re.IGNORECASE):
                action_verbs_found.append(verb)
        
        action_verb_ratio = len(action_verbs_found) / len(self.formatting_rules["keywords"]["action_verbs"])
        if action_verb_ratio > 0.3:
            strengths.append("Uses strong action verbs effectively")
        elif action_verb_ratio > 0.1:
            recommendations.append("Include more action verbs to strengthen impact")
        else:
            score -= 15
            warnings.append("Lacks strong action verbs")
            recommendations.append("Add action verbs like 'achieved', 'managed', 'developed'")
        
        # Check for quantifiable achievements
        quantifiable_patterns = [
            r'\d+%', r'\$\d+', r'\d+\s*(million|thousand|k)', 
            r'increased.*\d+', r'reduced.*\d+', r'improved.*\d+'
        ]
        
        quantifiable_found = sum(1 for pattern in quantifiable_patterns 
                               if re.search(pattern, text_content, re.IGNORECASE))
        
        if quantifiable_found >= 3:
            strengths.append("Includes quantifiable achievements")
        elif quantifiable_found >= 1:
            recommendations.append("Add more quantifiable achievements")
        else:
            score -= 20
            warnings.append("Lacks quantifiable achievements")
            recommendations.append("Include specific numbers, percentages, and metrics")
        
        # Industry-specific keyword matching
        if industry and industry in self.industry_keywords:
            industry_keywords = self.industry_keywords[industry]
            keywords_found = [kw for kw in industry_keywords 
                            if re.search(rf'\b{kw}\b', text_content, re.IGNORECASE)]
            
            keyword_ratio = len(keywords_found) / len(industry_keywords)
            if keyword_ratio > 0.4:
                strengths.append(f"Strong {industry} industry keyword presence")
            elif keyword_ratio > 0.2:
                recommendations.append(f"Include more {industry} industry keywords")
            else:
                score -= 10
                recommendations.append(f"Add relevant {industry} industry keywords")
        
        # Job description matching (if provided)
        if job_description:
            jd_keywords = self._extract_keywords_from_job_description(job_description)
            matching_keywords = [kw for kw in jd_keywords 
                               if re.search(rf'\b{kw}\b', text_content, re.IGNORECASE)]
            
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
                "action_verbs_found": action_verbs_found,
                "action_verb_ratio": action_verb_ratio,
                "quantifiable_achievements": quantifiable_found,
                "industry_keywords_found": keywords_found if industry else [],
                "job_match_ratio": match_ratio if job_description else 0
            }
        }
    
    async def _score_keywords(
        self, 
        text_content: str, 
        job_description: Optional[str] = None,
        industry: Optional[str] = None
    ) -> Dict[str, Any]:
        """Score keyword optimization and density."""
        score = 100.0
        recommendations = []
        warnings = []
        strengths = []
        
        # Keyword density analysis
        words = text_content.lower().split()
        word_count = len(words)
        
        if word_count == 0:
            return {
                "score": 0,
                "recommendations": ["Add content to analyze keywords"],
                "warnings": ["No content found"],
                "strengths": [],
                "details": {}
            }
        
        # Check for keyword stuffing
        word_frequency = {}
        for word in words:
            if len(word) > 3:  # Only count meaningful words
                word_frequency[word] = word_frequency.get(word, 0) + 1
        
        # Identify potential keyword stuffing
        stuffed_keywords = [word for word, count in word_frequency.items() 
                          if count / word_count > 0.05 and count > 3]
        
        if stuffed_keywords:
            score -= 20
            warnings.append("Potential keyword stuffing detected")
            recommendations.append("Reduce repetition of overused keywords")
        else:
            strengths.append("Natural keyword distribution")
        
        # Skills and technologies detection
        tech_keywords = [
            'python', 'java', 'javascript', 'react', 'node', 'sql', 'aws',
            'docker', 'kubernetes', 'git', 'agile', 'scrum', 'api', 'rest'
        ]
        
        tech_found = [kw for kw in tech_keywords 
                     if re.search(rf'\b{kw}\b', text_content, re.IGNORECASE)]
        
        if len(tech_found) >= 5:
            strengths.append("Rich technical keyword presence")
        elif len(tech_found) >= 2:
            recommendations.append("Consider adding more relevant technical keywords")
        else:
            score -= 10
            recommendations.append("Include relevant technical skills and keywords")
        
        # Soft skills detection
        soft_skills = [
            'leadership', 'communication', 'teamwork', 'problem-solving',
            'analytical', 'creative', 'adaptable', 'collaborative'
        ]
        
        soft_skills_found = [skill for skill in soft_skills 
                           if re.search(rf'\b{skill}\b', text_content, re.IGNORECASE)]
        
        if len(soft_skills_found) >= 3:
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
                "keyword_density": len(set(words)) / word_count if word_count > 0 else 0
            }
        }
    
    async def _score_readability(self, text_content: str) -> Dict[str, Any]:
        """Score readability and clarity."""
        score = 100.0
        recommendations = []
        warnings = []
        strengths = []
        
        if not text_content.strip():
            return {
                "score": 0,
                "recommendations": ["Add content to analyze readability"],
                "warnings": ["No content found"],
                "strengths": [],
                "details": {}
            }
        
        # Basic readability metrics
        sentences = re.split(r'[.!?]+', text_content)
        sentences = [s.strip() for s in sentences if s.strip()]
        words = text_content.split()
        
        avg_sentence_length = len(words) / max(len(sentences), 1)
        
        # Check sentence length
        if avg_sentence_length > 25:
            score -= 15
            warnings.append("Sentences are too long")
            recommendations.append("Use shorter, more concise sentences")
        elif avg_sentence_length < 8:
            score -= 5
            recommendations.append("Consider varying sentence length")
        else:
            strengths.append("Appropriate sentence length")
        
        # Check for passive voice
        passive_indicators = ['was', 'were', 'been', 'being']
        passive_count = sum(1 for word in words 
                          if word.lower() in passive_indicators)
        passive_ratio = passive_count / max(len(words), 1)
        
        if passive_ratio > 0.1:
            score -= 10
            recommendations.append("Reduce passive voice usage")
        else:
            strengths.append("Uses active voice effectively")
        
        # Check for clarity issues
        filler_words = ['very', 'really', 'quite', 'rather', 'somewhat']
        filler_count = sum(1 for word in words 
                         if word.lower() in filler_words)
        
        if filler_count > len(words) * 0.02:
            score -= 5
            recommendations.append("Remove unnecessary filler words")
        
        # Check for professional tone
        informal_words = ['awesome', 'cool', 'stuff', 'things', 'guys']
        informal_count = sum(1 for word in words 
                           if word.lower() in informal_words)
        
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
                "informal_word_count": informal_count
            }
        }
    
    async def _analyze_sections(self, text_content: str) -> Dict[str, SectionAnalysis]:
        """Analyze individual resume sections."""
        sections = {}
        
        # Contact section analysis
        contact_patterns = [r'email', r'@', r'phone', r'\d{3}[-.]?\d{3}[-.]?\d{4}']
        contact_found = any(re.search(pattern, text_content, re.IGNORECASE) 
                          for pattern in contact_patterns)
        
        sections["contact"] = SectionAnalysis(
            found=contact_found,
            score=100 if contact_found else 0,
            content_length=len(re.findall(r'[@\d\-\.]', text_content)),
            keywords_found=[p for p in contact_patterns 
                          if re.search(p, text_content, re.IGNORECASE)],
            issues=[] if contact_found else ["Missing contact information"],
            suggestions=[] if contact_found else ["Add email and phone number"]
        )
        
        # Experience section analysis
        exp_patterns = [r'experience', r'work', r'employment', r'career']
        exp_found = any(re.search(pattern, text_content, re.IGNORECASE) 
                       for pattern in exp_patterns)
        
        sections["experience"] = SectionAnalysis(
            found=exp_found,
            score=100 if exp_found else 0,
            content_length=len(text_content.split()) // 3,  # Estimate
            keywords_found=[p for p in exp_patterns 
                          if re.search(p, text_content, re.IGNORECASE)],
            issues=[] if exp_found else ["Missing work experience"],
            suggestions=[] if exp_found else ["Add work experience section"]
        )
        
        # Education section analysis
        edu_patterns = [r'education', r'degree', r'university', r'college']
        edu_found = any(re.search(pattern, text_content, re.IGNORECASE) 
                       for pattern in edu_patterns)
        
        sections["education"] = SectionAnalysis(
            found=edu_found,
            score=100 if edu_found else 0,
            content_length=len(text_content.split()) // 4,  # Estimate
            keywords_found=[p for p in edu_patterns 
                          if re.search(p, text_content, re.IGNORECASE)],
            issues=[] if edu_found else ["Missing education information"],
            suggestions=[] if edu_found else ["Add education section"]
        )
        
        return sections
    
    def _check_ats_compatibility(self, latex_content: str) -> Dict[str, Any]:
        """Check for ATS compatibility issues."""
        issues = []
        compatibility_score = 100
        
        # Check for problematic LaTeX elements
        problematic_elements = {
            'tables': r'\\begin\{table\}|\\begin\{tabular\}',
            'graphics': r'\\includegraphics|\\begin\{figure\}',
            'complex_formatting': r'\\multicolumn|\\multirow',
            'text_boxes': r'\\fbox|\\framebox',
            'headers_footers': r'\\fancyhdr|\\pagestyle'
        }
        
        for element, pattern in problematic_elements.items():
            if re.search(pattern, latex_content):
                issues.append(f"Contains {element.replace('_', ' ')} which may cause ATS issues")
                compatibility_score -= 15
        
        return {
            "compatibility_score": max(0, compatibility_score),
            "issues": issues,
            "ats_friendly": compatibility_score >= 80
        }
    
    def _prioritize_improvements(self, category_scores: Dict[str, float]) -> List[Dict[str, Any]]:
        """Prioritize improvements based on category scores."""
        improvements = []
        
        for category, score in category_scores.items():
            if score < 70:
                priority = "high" if score < 50 else "medium"
                improvements.append({
                    "category": category,
                    "current_score": score,
                    "priority": priority,
                    "potential_impact": 100 - score
                })
        
        # Sort by potential impact (descending)
        improvements.sort(key=lambda x: x["potential_impact"], reverse=True)
        
        return improvements
    
    def _extract_keywords_from_job_description(self, job_description: str) -> List[str]:
        """Extract relevant keywords from job description."""
        # Simple keyword extraction - in production, this could use NLP
        words = re.findall(r'\b[a-zA-Z]{3,}\b', job_description.lower())
        
        # Filter out common words
        stop_words = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
            'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his',
            'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'who', 'boy',
            'did', 'she', 'use', 'her', 'way', 'many', 'oil', 'sit', 'set'
        }
        
        keywords = [word for word in words if word not in stop_words and len(word) > 3]
        
        # Return unique keywords, limited to top 20
        return list(set(keywords))[:20]


# Global service instance
ats_scoring_service = ATSScoringService()
