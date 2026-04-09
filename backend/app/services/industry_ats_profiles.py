"""
Industry-specific ATS calibration profiles for Feature 46.

Provides keyword weight multipliers and section scoring weights per industry,
plus a keyword-frequency detector to auto-detect industry from a job description.
"""

import re
from typing import Dict

INDUSTRY_PROFILES: Dict[str, dict] = {
    "tech_saas": {
        "label": "Technology / SaaS",
        "keywords": {
            "kubernetes": 1.5,
            "microservices": 1.4,
            "ci/cd": 1.3,
            "api": 1.2,
            "cloud": 1.2,
            "agile": 1.1,
            "python": 1.1,
            "docker": 1.1,
            "aws": 1.2,
            "devops": 1.2,
            "rest": 1.1,
            "graphql": 1.1,
            "terraform": 1.2,
            "linux": 1.0,
            "typescript": 1.0,
            "react": 1.0,
        },
        "section_weights": {"experience": 1.3, "skills": 1.2, "education": 0.8},
        "detect_keywords": [
            "saas", "api", "kubernetes", "microservice", "startup",
            "engineer", "docker", "devops", "cloud native",
        ],
    },
    "finance_banking": {
        "label": "Finance / Banking",
        "keywords": {
            "bloomberg": 1.5,
            "cfa": 1.4,
            "frm": 1.3,
            "equity": 1.3,
            "trading": 1.3,
            "portfolio": 1.2,
            "risk management": 1.4,
            "financial modeling": 1.3,
            "derivatives": 1.2,
            "fixed income": 1.3,
            "compliance": 1.2,
            "audit": 1.1,
            "investment": 1.2,
            "excel": 1.1,
        },
        "section_weights": {"experience": 1.2, "skills": 1.0, "education": 1.2},
        "detect_keywords": [
            "bloomberg", "cfa", "equity", "trading", "portfolio",
            "risk management", "investment banking", "derivatives",
        ],
    },
    "healthcare": {
        "label": "Healthcare / Clinical",
        "keywords": {
            "hipaa": 1.5,
            "ehr": 1.4,
            "clinical": 1.3,
            "patient": 1.2,
            "fda": 1.3,
            "epic": 1.2,
            "medical": 1.2,
            "diagnosis": 1.1,
            "therapy": 1.1,
            "pharmaceutical": 1.2,
            "gcp": 1.3,
            "irb": 1.3,
            "nursing": 1.2,
        },
        "section_weights": {"experience": 1.2, "skills": 1.1, "education": 1.3},
        "detect_keywords": [
            "hipaa", "ehr", "clinical", "patient", "fda",
            "medical", "hospital", "nursing", "pharmaceutical",
        ],
    },
    "consulting": {
        "label": "Consulting / Advisory",
        "keywords": {
            "engagement": 1.3,
            "client": 1.2,
            "framework": 1.2,
            "strategy": 1.3,
            "stakeholder": 1.2,
            "deliverable": 1.2,
            "mckinsey": 1.5,
            "deloitte": 1.4,
            "bcg": 1.4,
            "slide": 1.1,
            "powerpoint": 1.0,
            "presentation": 1.1,
        },
        "section_weights": {"experience": 1.4, "skills": 1.0, "education": 1.1},
        "detect_keywords": [
            "mckinsey", "deloitte", "bcg", "engagement", "client",
            "framework", "consulting", "advisory",
        ],
    },
    "marketing": {
        "label": "Marketing / Growth",
        "keywords": {
            "seo": 1.4,
            "sem": 1.3,
            "campaign": 1.2,
            "roi": 1.3,
            "conversion": 1.3,
            "analytics": 1.2,
            "hubspot": 1.2,
            "salesforce": 1.2,
            "content": 1.1,
            "brand": 1.2,
            "social media": 1.1,
            "growth": 1.2,
            "a/b testing": 1.3,
        },
        "section_weights": {"experience": 1.2, "skills": 1.1, "education": 0.9},
        "detect_keywords": [
            "seo", "campaign", "roi", "conversion", "hubspot",
            "growth hacking", "digital marketing", "brand",
        ],
    },
    "generic": {
        "label": "General",
        "keywords": {},
        "section_weights": {},
        "detect_keywords": [],
    },
}


def detect_industry(job_description: str) -> str:
    """
    Detect industry from job description via keyword frequency matching.

    Scores each non-generic profile by counting how many of its
    detect_keywords appear in the JD (case-insensitive substring match).
    Returns the best-scoring profile key when score >= 2, else "generic".
    """
    if not job_description or not job_description.strip():
        return "generic"
    jd_lower = job_description.lower()
    scores: Dict[str, int] = {
        name: sum(
            1 for kw in profile["detect_keywords"]
            if re.search(r'\b' + re.escape(kw) + r'\b', jd_lower)
        )
        for name, profile in INDUSTRY_PROFILES.items()
        if name != "generic"
    }
    if not scores:
        return "generic"
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 2 else "generic"
