"""Feature registry — the code-defined catalog of toggleable product features.

This is the static catalog consumed by the Admin Control Plane. It is NOT the 6
existing operational feature flags (trial_limits, deep_analysis_trial,
compile_timeouts, task_priority, billing, upgrade_ctas) — those live in the
feature_flags table and are handled by feature_flag_service.

Each registry entry has a stable ``key``. Gateable features can be turned off
globally (kill-switch) or per plan family (matrix). Non-gateable features (e.g.
core LaTeX compilation) are always available and shown in the dashboard as
always-on.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureDef:
    """A single toggleable product feature in the registry."""

    key: str
    label: str
    category: str  # core | editor | career | advanced | integrations | analytics
    description: str
    gateable: bool = True


# Plan families the matrix is keyed by (mirrors config.PLAN_FAMILY_ALIASES targets).
PLAN_FAMILIES = ["free", "basic", "pro", "byok", "team"]


FEATURE_REGISTRY: list[FeatureDef] = [
    # ---- core -------------------------------------------------------------
    FeatureDef("compile", "LaTeX Compilation", "core",
               "Compile LaTeX source to PDF.", gateable=False),
    FeatureDef("llm_optimize", "AI Resume Optimization", "core",
               "Rewrite and optimize a resume with the AI engine."),
    FeatureDef("ats_score", "ATS Scoring", "core",
               "Score a resume against ATS criteria."),
    FeatureDef("ats_deep", "ATS Deep Analysis", "core",
               "Run the in-depth ATS analysis with detailed recommendations."),
    # ---- editor -----------------------------------------------------------
    FeatureDef("resume_builder", "Resume Builder", "editor",
               "Structured resume builder and editor."),
    FeatureDef("cover_letters", "Cover Letters", "editor",
               "Generate and manage tailored cover letters."),
    FeatureDef("batch_tailor", "Batch Tailoring", "editor",
               "Tailor a resume to many job descriptions at once."),
    FeatureDef("templates", "Templates", "editor",
               "Browse and apply resume templates."),
    FeatureDef("exports", "Multi-format Export", "editor",
               "Export resumes to formats beyond PDF."),
    FeatureDef("ai_writing", "AI Writing Tools", "editor",
               "Inline AI writing assistance in the editor."),
    FeatureDef("macros", "Editor Macros", "editor",
               "Custom editor macros and shortcuts."),
    FeatureDef("snippets", "Snippets Marketplace", "editor",
               "Reusable snippet library and marketplace."),
    # ---- career -----------------------------------------------------------
    FeatureDef("career_paths", "Career Paths", "career",
               "Explore career path transitions and gap analysis."),
    FeatureDef("interview_prep", "Interview Prep", "career",
               "AI-assisted interview preparation."),
    FeatureDef("application_tracker", "Application Tracker", "career",
               "Track job applications and their status."),
    FeatureDef("one_click_apply", "One-click Apply", "career",
               "Submit applications with a single click."),
    # ---- advanced ---------------------------------------------------------
    FeatureDef("byok", "Bring Your Own Key", "advanced",
               "Use your own LLM provider API keys."),
    FeatureDef("collaboration", "Collaboration & Comments", "advanced",
               "Share resumes and collaborate with comments."),
    FeatureDef("team_workspaces", "Team Workspaces", "advanced",
               "Shared team workspaces for resumes."),
    FeatureDef("portfolio", "Public Portfolio", "advanced",
               "Publish a public portfolio profile."),
    FeatureDef("developer_api", "Developer API", "advanced",
               "Programmatic access via developer API keys."),
    FeatureDef("references", "Reference Manager", "advanced",
               "Manage references and citation sources."),
    # ---- integrations -----------------------------------------------------
    FeatureDef("integration_github", "GitHub Integration", "integrations",
               "Sync resumes with a GitHub repository."),
    FeatureDef("integration_dropbox", "Dropbox Integration", "integrations",
               "Sync resumes with Dropbox."),
    FeatureDef("integration_zotero", "Zotero Integration", "integrations",
               "Import references from Zotero."),
    FeatureDef("integration_mendeley", "Mendeley Integration", "integrations",
               "Import references from Mendeley."),
    FeatureDef("ai_import_github", "GitHub Project Import", "integrations",
               "Import your top public GitHub projects as AI-summarized resume evidence."),
    # ---- analytics --------------------------------------------------------
    FeatureDef("analytics", "Analytics Dashboard", "analytics",
               "Usage and performance analytics dashboard."),
]


# Index for O(1) lookup.
_REGISTRY_BY_KEY: dict[str, FeatureDef] = {f.key: f for f in FEATURE_REGISTRY}


def get_feature(key: str) -> FeatureDef | None:
    """Return the FeatureDef for a key, or None if unknown."""
    return _REGISTRY_BY_KEY.get(key)


def all_feature_keys() -> list[str]:
    """Return every registry feature key (gateable and non-gateable)."""
    return [f.key for f in FEATURE_REGISTRY]


def gateable_keys() -> list[str]:
    """Return only the keys of gateable features."""
    return [f.key for f in FEATURE_REGISTRY if f.gateable]


def is_gateable(key: str) -> bool:
    """Return True if the key is a known, gateable feature."""
    feature = _REGISTRY_BY_KEY.get(key)
    return bool(feature and feature.gateable)
