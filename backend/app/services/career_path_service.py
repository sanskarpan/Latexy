"""
Career Path + Skills Gap Analysis service — Feature 80.

Provides:
  • detect_current_role   — LLM extracts current job title from resume
  • match_career_role     — fuzzy-match title against career_roles table
  • find_path             — BFS over career_transitions graph
  • analyze_gap           — LLM gap analysis + timeline
  • run_full_analysis     — orchestrates all steps, persists CareerAnalysis
"""

from __future__ import annotations

import re
from collections import deque
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.models import CareerAnalysis, CareerRole, CareerTransition

logger = get_logger(__name__)


class CareerPathService:
    """Service for career path visualization and skills gap analysis."""

    # ── Role detection ────────────────────────────────────────────────────────

    async def detect_current_role(self, latex_content: str) -> str:
        """
        LLM call: extract the most recent job title from the resume LaTeX.
        Returns a best-guess plain-text title string.
        Falls back to heuristic parsing if LLM is unavailable.
        """
        title = self._heuristic_detect_role(latex_content)

        try:
            result = await self._llm_complete(
                system="You are a resume parser. Extract only the job title — no explanation.",
                user=(
                    "Extract only the current or most recent job title from the following resume LaTeX. "
                    "Return JUST the job title, nothing else. If you cannot determine it, reply 'Unknown'.\n\n"
                    f"{latex_content[:4000]}"
                ),
                max_tokens=50,
            )
            extracted = result.strip().strip('"').strip("'")
            if extracted and extracted.lower() != "unknown":
                return extracted
        except Exception as exc:
            logger.warning(f"LLM role detection failed, using heuristic: {exc}")

        return title

    def _heuristic_detect_role(self, latex_content: str) -> str:
        """
        Regex-based fallback: look for resumeSubheading subheading arg (role field)
        or a cventry degree arg.
        """
        # \resumeSubheading{Company}{Date}{Role}{Location}
        m = re.search(r'\\resumeSubheading\s*\{[^}]*\}\s*\{[^}]*\}\s*\{([^}]+)\}', latex_content)
        if m:
            return m.group(1).strip()
        # \cventry{years}{degree/title}{company}...
        m = re.search(r'\\cventry\s*\{[^}]*\}\s*\{([^}]+)\}', latex_content)
        if m:
            return m.group(1).strip()
        return "Software Engineer"

    # ── Role matching ─────────────────────────────────────────────────────────

    async def match_career_role(
        self, title: str, db: AsyncSession
    ) -> Optional[CareerRole]:
        """
        Fuzzy-match a free-text title against the career_roles table using
        PostgreSQL trigram similarity (pg_trgm extension).
        Falls back to ILIKE containment if trigrams are unavailable.
        Returns the best match above a 0.25 similarity threshold, or None.
        """
        try:
            # Try pg_trgm similarity first
            result = await db.execute(
                text(
                    "SELECT id, similarity(title, :title) AS sim "
                    "FROM career_roles "
                    "ORDER BY sim DESC "
                    "LIMIT 1"
                ),
                {"title": title},
            )
            row = result.fetchone()
            if row and row.sim and row.sim >= 0.25:
                role_result = await db.execute(
                    select(CareerRole).where(CareerRole.id == row.id)
                )
                return role_result.scalar_one_or_none()
        except Exception:
            pass  # pg_trgm not installed — fall through to ILIKE

        # ILIKE fallback: check if any word in the title appears
        words = [w for w in title.split() if len(w) > 3]
        for word in words:
            result = await db.execute(
                select(CareerRole).where(
                    CareerRole.title.ilike(f"%{word}%")
                ).limit(1)
            )
            role = result.scalar_one_or_none()
            if role:
                return role

        return None

    async def search_roles(
        self, query: str, db: AsyncSession, limit: int = 10
    ) -> list[CareerRole]:
        """Search career roles by partial title match for autocomplete."""
        result = await db.execute(
            select(CareerRole)
            .where(CareerRole.title.ilike(f"%{query}%"))
            .order_by(CareerRole.title)
            .limit(limit)
        )
        return list(result.scalars().all())

    # ── Graph traversal ───────────────────────────────────────────────────────

    async def find_path(
        self, from_role_id: str, to_role_id: str, db: AsyncSession
    ) -> list[CareerRole]:
        """
        BFS over career_transitions to find shortest path from from_role_id
        to to_role_id. Returns ordered list of roles INCLUDING from and to.
        Returns [from_role, to_role] if no intermediate path found.
        """
        if from_role_id == to_role_id:
            r = await db.get(CareerRole, from_role_id)
            return [r] if r else []

        # Load all transitions into memory for BFS (graph is small, ~200 edges)
        transitions_result = await db.execute(select(CareerTransition))
        all_transitions = transitions_result.scalars().all()

        adjacency: dict[str, list[str]] = {}
        for t in all_transitions:
            adjacency.setdefault(t.from_role_id, []).append(t.to_role_id)

        # BFS
        visited = {from_role_id}
        queue: deque[list[str]] = deque([[from_role_id]])
        while queue:
            path = queue.popleft()
            node = path[-1]
            for neighbor in adjacency.get(node, []):
                if neighbor == to_role_id:
                    role_ids = path + [to_role_id]
                    # Resolve role objects
                    roles = []
                    for rid in role_ids:
                        role = await db.get(CareerRole, rid)
                        if role:
                            roles.append(role)
                    return roles
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        # No BFS path found — return just the two endpoints
        from_role = await db.get(CareerRole, from_role_id)
        to_role = await db.get(CareerRole, to_role_id)
        return [r for r in [from_role, to_role] if r]

    # ── Gap analysis ──────────────────────────────────────────────────────────

    async def analyze_gap(
        self,
        current_skills: list[str],
        target_role: CareerRole,
        path: list[CareerRole],
        latex_content: str,
        db: AsyncSession,
    ) -> dict:
        """
        LLM call: compare current skills vs target required_skills.
        Returns dict with gap_skills, timeline_months, llm_analysis.
        """
        required = set(target_role.required_skills or [])
        have = set(s.strip() for s in current_skills)
        gap_skills = sorted(required - have)

        # Estimate rough timeline from path transitions
        timeline_months = await self._estimate_timeline(path, db)

        # LLM narrative analysis
        llm_analysis = await self._llm_gap_analysis(
            current_skills=current_skills,
            target_role=target_role,
            gap_skills=gap_skills,
            path=path,
            timeline_months=timeline_months,
            latex_content=latex_content,
        )

        return {
            "gap_skills": gap_skills,
            "timeline_months": timeline_months,
            "llm_analysis": llm_analysis,
        }

    async def _estimate_timeline(
        self, path: list[CareerRole], db: AsyncSession
    ) -> int:
        """Sum avg_years across path transitions, return total in months."""
        if len(path) <= 1:
            return 0
        total_years = 0.0
        for i in range(len(path) - 1):
            t_result = await db.execute(
                select(CareerTransition).where(
                    CareerTransition.from_role_id == path[i].id,
                    CareerTransition.to_role_id == path[i + 1].id,
                )
            )
            transition = t_result.scalar_one_or_none()
            total_years += float(transition.avg_years or 2.5) if transition else 2.5
        return round(total_years * 12)

    async def _llm_gap_analysis(
        self,
        current_skills: list[str],
        target_role: CareerRole,
        gap_skills: list[str],
        path: list[CareerRole],
        timeline_months: int,
        latex_content: str,
    ) -> str:
        """Generate markdown narrative career analysis via LLM."""
        path_str = " → ".join(r.title for r in path) if path else target_role.title
        years_str = f"{timeline_months // 12}" if timeline_months else "N/A"

        prompt = f"""You are a career coach. A user's resume shows they have these skills:
{', '.join(current_skills[:30]) or 'unspecified'}

They want to reach: **{target_role.title}** ({target_role.level.replace('-', ' ')}, {target_role.industry.replace('_', ' ')})
Required skills for that role: {', '.join(target_role.required_skills or [])}
Skills gap to address: {', '.join(gap_skills) or 'None — already qualified!'}
Suggested path: {path_str}
Estimated timeline: ~{years_str} year(s)

Write a concise (3–5 paragraphs) career development plan in Markdown. Cover:
1. Strengths to leverage
2. Skills to develop (prioritized)
3. Recommended learning resources / certifications
4. Timeline milestones
5. One actionable next step this week
"""
        try:
            return await self._llm_complete(
                system="You are an expert career coach. Write structured Markdown career advice.",
                user=prompt,
                max_tokens=800,
            )
        except Exception as exc:
            logger.warning(f"LLM gap analysis failed: {exc}")
            # Fallback plaintext
            lines = [
                f"## Career Path: {path_str}",
                "",
                f"**Estimated timeline:** ~{years_str} year(s) ({timeline_months} months)",
                "",
                "### Skills You Have",
                ", ".join(current_skills[:20]) or "Not detected",
                "",
                "### Skills to Develop",
                "\n".join(f"- {s}" for s in gap_skills) or "You already have the required skills!",
                "",
                "### Next Steps",
                "1. Review the gap skills listed above",
                "2. Identify courses or projects to build each skill",
                "3. Update your resume after each milestone",
            ]
            return "\n".join(lines)

    # ── Current skills extraction ─────────────────────────────────────────────

    async def extract_current_skills(self, latex_content: str) -> list[str]:
        """
        Extract skills from resume using LLM. Falls back to keyword scanning.
        """
        try:
            result = await self._llm_complete(
                system="You are a resume parser. Return only a JSON array.",
                user=(
                    "Extract all technical and professional skills from this resume LaTeX. "
                    "Return a JSON array of skill strings only. Maximum 40 skills.\n\n"
                    f"{latex_content[:3000]}"
                ),
                max_tokens=300,
            )
            import json
            # Extract JSON array from response
            m = re.search(r'\[.*?\]', result, re.DOTALL)
            if m:
                return json.loads(m.group(0))
        except Exception as exc:
            logger.warning(f"LLM skill extraction failed: {exc}")

        return self._heuristic_extract_skills(latex_content)

    def _heuristic_extract_skills(self, latex_content: str) -> list[str]:
        """Extract skills by scanning Skills/Technologies sections."""
        skills = []
        in_skills = False
        for line in latex_content.split('\n'):
            if re.search(r'\\section\{.*?(?:skill|tech|language|tool)', line, re.I):
                in_skills = True
            elif re.search(r'\\section\{', line):
                in_skills = False
            if in_skills:
                # Extract items inside \item or textbf
                found = re.findall(r'\\item\s+([^\\\n,;]+)', line)
                skills.extend(s.strip() for s in found if s.strip())
                found2 = re.findall(r'\\textbf\{([^}]+)\}', line)
                skills.extend(s.strip() for s in found2 if s.strip())
        return list(dict.fromkeys(skills))[:30]

    # ── Full analysis orchestrator ────────────────────────────────────────────

    async def run_full_analysis(
        self,
        resume_id: str,
        user_id: str,
        target_role_title: str,
        latex_content: str,
        db: AsyncSession,
    ) -> CareerAnalysis:
        """
        Orchestrate the full career analysis pipeline:
          1. Extract current role + skills from resume
          2. Match current & target roles in DB
          3. BFS path
          4. Gap analysis
          5. Persist & return CareerAnalysis
        """
        # 1. Extract
        current_role_title = await self.detect_current_role(latex_content)
        current_skills = await self.extract_current_skills(latex_content)

        # 2. Match roles
        current_role = await self.match_career_role(current_role_title, db)
        target_role = await self.match_career_role(target_role_title, db)

        target_role_id: Optional[str] = None
        target_role_freetext: Optional[str] = None
        path: list[CareerRole] = []

        if target_role:
            target_role_id = target_role.id
        else:
            target_role_freetext = target_role_title
            # Create a synthetic target role for gap analysis
            target_role = CareerRole(
                id=str(uuid4()),
                title=target_role_title,
                level="senior",
                industry="software_engineering",
                required_skills=[],
            )

        # 3. Find path
        if current_role and target_role_id:
            path = await self.find_path(current_role.id, target_role_id, db)
        elif current_role:
            path = [current_role]

        # 4. Gap analysis
        gap_data = await self.analyze_gap(
            current_skills=current_skills,
            target_role=target_role,
            path=path,
            latex_content=latex_content,
            db=db,
        )

        # 5. Persist
        analysis = CareerAnalysis(
            user_id=user_id,
            resume_id=resume_id,
            target_role_id=target_role_id,
            target_role_freetext=target_role_freetext,
            current_skills=current_skills,
            gap_skills=gap_data["gap_skills"],
            path_role_ids=[r.id for r in path] if path else None,
            timeline_months=gap_data["timeline_months"],
            llm_analysis=gap_data["llm_analysis"],
        )
        db.add(analysis)
        await db.commit()
        await db.refresh(analysis)
        return analysis


    # ── LLM helper ────────────────────────────────────────────────────────────

    async def _llm_complete(
        self, system: str, user: str, max_tokens: int = 400
    ) -> str:
        """
        Thin wrapper that calls the system LLM (OpenAI) with a simple
        system + user message pair and returns the text content.
        """
        from ..core.config import settings

        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not configured")

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""


career_path_service = CareerPathService()
