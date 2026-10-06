"""Deterministic, reversible formatting profiles for one-page resume fitting."""

from __future__ import annotations

import re
from dataclasses import dataclass

START_MARKER = "% LATEXY_AUTO_FIT_START"
END_MARKER = "% LATEXY_AUTO_FIT_END"
_BLOCK_RE = re.compile(
    rf"\n?{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}\n?",
    re.DOTALL,
)
_BEGIN_DOCUMENT = r"\begin{document}"


@dataclass(frozen=True)
class AutoFitProfile:
    intensity: int
    line_spread: float
    vertical_expansion_mm: int
    horizontal_expansion_mm: int
    use_small_font: bool


# Ordered from the least to the most visually aggressive safe adjustment. The
# final profile bottoms out at LaTeX's `\small` (normally 9pt for a 10pt base),
# rather than producing unreadable 6–8pt resumes merely to claim success.
AUTO_FIT_PROFILES = (
    AutoFitProfile(25, 0.97, 6, 2, False),
    AutoFitProfile(50, 0.94, 12, 4, False),
    AutoFitProfile(75, 0.91, 18, 6, True),
    AutoFitProfile(100, 0.88, 24, 8, True),
)


def remove_auto_fit(latex_content: str) -> str:
    """Remove a previously generated Latexy auto-fit block."""
    return _BLOCK_RE.sub("\n", latex_content)


def apply_auto_fit(latex_content: str, profile: AutoFitProfile) -> str:
    """Apply one profile without changing document content or stacking blocks."""
    source = remove_auto_fit(latex_content)
    position = source.find(_BEGIN_DOCUMENT)
    if position < 0:
        raise ValueError(r"Auto-fit requires a \begin{document} marker")

    half_vertical = profile.vertical_expansion_mm / 2
    half_horizontal = profile.horizontal_expansion_mm / 2
    directives = [
        START_MARKER,
        f"\\linespread{{{profile.line_spread:.2f}}}",
        f"\\addtolength{{\\textheight}}{{{profile.vertical_expansion_mm}mm}}",
        f"\\addtolength{{\\topmargin}}{{-{half_vertical:g}mm}}",
        f"\\addtolength{{\\textwidth}}{{{profile.horizontal_expansion_mm}mm}}",
        f"\\addtolength{{\\oddsidemargin}}{{-{half_horizontal:g}mm}}",
        f"\\addtolength{{\\evensidemargin}}{{-{half_horizontal:g}mm}}",
    ]
    if profile.use_small_font:
        directives.append(r"\AtBeginDocument{\small}")
    directives.append(END_MARKER)
    block = "\n".join(directives) + "\n"
    return source[:position] + block + source[position:]


def profile_for_intensity(intensity: int) -> AutoFitProfile:
    """Select the first bounded profile at or above a slider intensity."""
    if not 0 <= intensity <= 100:
        raise ValueError("Auto-fit intensity must be between 0 and 100")
    return next(
        (profile for profile in AUTO_FIT_PROFILES if intensity <= profile.intensity),
        AUTO_FIT_PROFILES[-1],
    )
