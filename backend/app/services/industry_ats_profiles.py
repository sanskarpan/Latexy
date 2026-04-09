"""
Industry-specific ATS calibration profiles.

Each profile contains:
  label           — human-readable display name
  keywords        — {keyword: weight_multiplier} (1.0 = neutral, >1 = boosted)
  section_weights — {section_key: weight_multiplier} applied to overall score weights
  detect_keywords — list of JD indicator words used for auto-detection
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
            "gcp": 1.2,
            "azure": 1.2,
            "devops": 1.2,
            "react": 1.1,
            "typescript": 1.1,
            "distributed": 1.3,
            "scalability": 1.2,
            "terraform": 1.3,
            "kafka": 1.3,
            "redis": 1.1,
            "postgresql": 1.1,
        },
        "section_weights": {
            "experience": 1.3,
            "skills": 1.2,
            "education": 0.8,
        },
        "detect_keywords": [
            "saas", "api", "kubernetes", "microservice", "startup",
            "engineer", "software", "developer", "backend", "frontend",
            "fullstack", "devops", "cloud", "stack",
        ],
    },
    "finance_banking": {
        "label": "Finance / Banking",
        "keywords": {
            "bloomberg": 1.5,
            "cfa": 1.4,
            "equity": 1.3,
            "trading": 1.3,
            "portfolio": 1.2,
            "risk management": 1.3,
            "financial modeling": 1.4,
            "valuation": 1.3,
            "derivatives": 1.4,
            "compliance": 1.2,
            "regulatory": 1.2,
            "frm": 1.3,
            "investment": 1.2,
            "hedge fund": 1.4,
            "private equity": 1.4,
            "due diligence": 1.3,
            "excel": 1.1,
            "vba": 1.2,
            "quantitative": 1.2,
        },
        "section_weights": {
            "experience": 1.3,
            "education": 1.2,
            "skills": 1.0,
        },
        "detect_keywords": [
            "bloomberg", "cfa", "equity", "trading", "portfolio",
            "risk management", "investment", "banking", "finance",
            "hedge fund", "private equity", "derivatives", "frm",
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
            "rn": 1.3,
            "md": 1.2,
            "epic": 1.3,
            "cerner": 1.3,
            "emr": 1.3,
            "clinical trials": 1.4,
            "icd-10": 1.3,
            "cpt": 1.2,
            "diagnosis": 1.2,
            "treatment": 1.1,
            "bls": 1.2,
            "acls": 1.2,
            "nursing": 1.2,
        },
        "section_weights": {
            "experience": 1.2,
            "education": 1.3,
            "skills": 1.1,
        },
        "detect_keywords": [
            "hipaa", "ehr", "clinical", "patient", "fda",
            "hospital", "medical", "nursing", "physician", "healthcare",
            "emr", "rn", "md", "clinical trials",
        ],
    },
    "consulting": {
        "label": "Consulting / Strategy",
        "keywords": {
            "mckinsey": 1.3,
            "deloitte": 1.3,
            "engagement": 1.2,
            "client": 1.1,
            "framework": 1.2,
            "stakeholder": 1.2,
            "deliverable": 1.3,
            "mba": 1.2,
            "slide": 1.2,
            "deck": 1.2,
            "roi": 1.2,
            "kpi": 1.2,
            "strategy": 1.3,
            "transformation": 1.2,
            "process improvement": 1.2,
            "change management": 1.3,
            "six sigma": 1.3,
            "lean": 1.2,
        },
        "section_weights": {
            "experience": 1.3,
            "education": 1.2,
            "skills": 0.9,
        },
        "detect_keywords": [
            "mckinsey", "deloitte", "bcg", "engagement", "client",
            "consultant", "consulting", "strategy", "stakeholder",
            "deliverable", "transformation", "advisory",
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
    detect_keywords appear in the JD (lowercased). Returns the
    profile key with the highest score if it is >= 2, else "generic".
    """
    jd_lower = job_description.lower()
    scores: Dict[str, int] = {}
    for name, profile in INDUSTRY_PROFILES.items():
        if name == "generic":
            continue
        scores[name] = sum(
            1 for kw in profile["detect_keywords"]
            if re.search(rf"\b{re.escape(kw)}\b", jd_lower)
        )

    if not scores:
        return "generic"

    best_score = max(scores.values())
    if best_score < 2:
        return "generic"
    winners = [name for name, s in scores.items() if s == best_score]
    return winners[0] if len(winners) == 1 else "generic"


def get_profile(key: str) -> dict:
    """Return the profile dict for the given key, falling back to generic."""
    return INDUSTRY_PROFILES.get(key, INDUSTRY_PROFILES["generic"])
