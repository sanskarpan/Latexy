"""
Seed script: loads all LaTeX template files from backend/app/data/templates/
into the resume_templates table. Safe to run multiple times (upserts on name+category).

Usage:
    cd backend
    python -m app.scripts.seed_templates
"""

import asyncio
import sys
from pathlib import Path

# Ensure backend/ is on sys.path
_backend = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_backend))

from dotenv import load_dotenv

load_dotenv(_backend / ".env")
load_dotenv(_backend.parent / ".env")

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ------------------------------------------------------------------
# Category metadata — determines display order + description
# ------------------------------------------------------------------
CATEGORY_META: dict[str, dict] = {
    "software_engineering": {"order": 0, "description": "Templates for software, ML, and data engineers."},
    "finance":              {"order": 1, "description": "Templates for finance, banking, and quant roles."},
    "academic":             {"order": 2, "description": "CV templates for researchers and academics."},
    "creative":             {"order": 3, "description": "Templates for design and creative professionals."},
    "minimal":              {"order": 4, "description": "Ultra-clean single-column templates."},
    "ats_safe":             {"order": 5, "description": "Plain-text friendly templates optimised for ATS parsing."},
    "two_column":           {"order": 6, "description": "Two-column layouts for denser information packing."},
    "executive":            {"order": 7, "description": "Senior leader and C-suite templates."},
    "marketing":            {"order": 8, "description": "Templates for marketing and growth professionals."},
    "medical":              {"order": 9, "description": "Medical and healthcare career templates."},
    "legal":                {"order": 10, "description": "Templates for legal professionals."},
    "graduate":             {"order": 11, "description": "Entry-level and graduate / career-change templates."},
}


def _pretty_name(stem: str) -> str:
    """Convert snake_case stem to Title Case template name."""
    return stem.replace("_", " ").title()


async def seed():
    from app.core.config import settings

    db_url = settings.DATABASE_URL
    # Ensure asyncpg driver
    db_url = re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", db_url)
    db_url = db_url.replace("sslmode=require", "ssl=require")
    # Strip channel_binding — not supported by asyncpg
    db_url = re.sub(r"[&?]channel_binding=[^&]*", "", db_url)

    engine = create_async_engine(db_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    templates_root = Path(__file__).parent.parent / "data" / "templates"
    if not templates_root.exists():
        print(f"ERROR: templates directory not found: {templates_root}")
        return

    inserted = updated = skipped = 0

    async with Session() as session:
        for category_dir in sorted(templates_root.iterdir()):
            if not category_dir.is_dir():
                continue
            category = category_dir.name
            if category not in CATEGORY_META:
                print(f"  WARN: unknown category directory '{category}' — skipping")
                continue
            cat_order = CATEGORY_META[category]["order"]

            tex_files = sorted(category_dir.glob("*.tex"))
            if not tex_files:
                print(f"  WARN: no .tex files in {category}/")
                continue

            for idx, tex_file in enumerate(tex_files):
                latex_content = tex_file.read_text(encoding="utf-8")
                name = _pretty_name(tex_file.stem)
                sort_order = cat_order * 100 + idx

                # Check if already seeded (match on name + category)
                from app.database.models import ResumeTemplate
                existing = (await session.execute(
                    select(ResumeTemplate)
                    .where(ResumeTemplate.name == name, ResumeTemplate.category == category)
                )).scalar_one_or_none()

                if existing:
                    # Update latex_content in case template was edited
                    if existing.latex_content != latex_content:
                        existing.latex_content = latex_content
                        existing.sort_order = sort_order
                        updated += 1
                        print(f"  UPDATED  {category}/{name}")
                    else:
                        skipped += 1
                else:
                    t = ResumeTemplate(
                        name=name,
                        description=None,
                        category=category,
                        tags=[category],
                        thumbnail_url=None,
                        latex_content=latex_content,
                        is_active=True,
                        sort_order=sort_order,
                    )
                    session.add(t)
                    inserted += 1
                    print(f"  INSERTED {category}/{name}")

        await session.commit()

    await engine.dispose()
    print(f"\nDone. Inserted={inserted}  Updated={updated}  Skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(seed())
