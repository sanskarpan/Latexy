"""Repository-owned static preamble shared by builder and image format build.

Keep this module dependency-free: image construction and cache admission must
never import the resume parser, workers, or application credentials.
"""

MANAGED_ENGLISH_PREAMBLE_LINES = (
    r"\documentclass[11pt,letterpaper]{article}",
    r"\usepackage[margin=0.65in]{geometry}",
    r"\usepackage[T1]{fontenc}",
    r"\usepackage[utf8]{inputenc}",
    r"\usepackage{enumitem}",
    r"\usepackage[hidelinks]{hyperref}",
    r"\usepackage{xcolor}",
    r"\setlist[itemize]{leftmargin=1.2em, itemsep=0.15em, topsep=0.15em}",
    r"\pagestyle{empty}",
    r"\setlength{\parindent}{0pt}",
)
MANAGED_ENGLISH_PREAMBLE = "\n".join(MANAGED_ENGLISH_PREAMBLE_LINES) + "\n"
MANAGED_ENGLISH_FORMAT_ID = "latexy-managed-english-v1"
