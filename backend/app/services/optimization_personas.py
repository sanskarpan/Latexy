"""
Optimization persona presets — Feature 56.

Each persona adds a short system-prompt addon to the LLM optimization stage,
biasing the language and emphasis toward a specific industry/level context.
"""

from __future__ import annotations

from typing import TypedDict


class PersonaConfig(TypedDict):
    label: str
    description: str
    prompt_addon: str


PERSONAS: dict[str, PersonaConfig] = {
    "startup": {
        "label": "Startup / Scale-up",
        "description": "Lean, impact-driven language for fast-moving environments. Emphasize metrics, growth, and ownership.",
        "prompt_addon": (
            "This resume is targeting startup or scale-up environments. "
            "Emphasize measurable impact (growth %, ARR, users), bias for action, "
            "breadth of ownership, and adaptability. Use concise, direct language — "
            "avoid corporate buzzwords. Highlight shipped products and tangible outcomes."
        ),
    },
    "enterprise": {
        "label": "Enterprise / Corporate",
        "description": "Formal, process-oriented language suited for large organizations and structured hiring pipelines.",
        "prompt_addon": (
            "This resume is targeting enterprise or corporate environments. "
            "Use formal, structured language. Highlight cross-functional collaboration, "
            "process improvements, compliance, stakeholder management, and scale of operations. "
            "Quantify team sizes, budget responsibility, and organizational impact."
        ),
    },
    "academic": {
        "label": "Academic / Research",
        "description": "Research-focused style highlighting publications, grants, teaching, and scholarly contributions.",
        "prompt_addon": (
            "This resume is targeting academic or research positions. "
            "Highlight publications, conference presentations, grants, teaching experience, "
            "research methodology, and scholarly contributions. Use field-specific terminology "
            "appropriately. Maintain a formal, precise tone befitting academic discourse."
        ),
    },
    "career_change": {
        "label": "Career Change / Pivot",
        "description": "Surfaces transferable skills and reframes past experience to align with a new field.",
        "prompt_addon": (
            "This resume is for someone making a career change or pivot. "
            "Surface and emphasize transferable skills, reframe past experiences in terms "
            "relevant to the target role, and highlight adaptability, learning agility, "
            "and cross-domain accomplishments. Bridge the candidate's background to the new field."
        ),
    },
    "executive": {
        "label": "Executive / C-Suite",
        "description": "Strategic, board-level language focusing on P&L, vision, and organizational leadership.",
        "prompt_addon": (
            "This resume is targeting executive or C-suite roles. "
            "Focus on strategic vision, P&L ownership, board-level communication, "
            "organizational transformation, and enterprise-wide impact. "
            "Use concise, powerful statements. Highlight leadership philosophy, "
            "revenue/cost outcomes, and the scale of teams and budgets managed."
        ),
    },
}

VALID_PERSONA_KEYS: frozenset[str] = frozenset(PERSONAS.keys())
