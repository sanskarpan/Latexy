"""
Career graph seed data — Feature 80.

Defines 80+ career roles across Software Engineering, Data Science, Product
Management, Finance/Quant, Consulting, and Marketing, plus the common
transition edges between them.

Usage: POST /admin/career-graph/seed  (admin only — idempotent via upsert)
"""

from typing import Any

# ── Role definitions ──────────────────────────────────────────────────────────
# Each role: (title, level, industry, required_skills, yoe_min, yoe_max)

ROLES: list[dict[str, Any]] = [
    # ─ Software Engineering ───────────────────────────────────────────────────
    {"title": "Software Engineering Intern",        "level": "intern",    "industry": "software_engineering",
     "required_skills": ["Python", "Git", "Data Structures"],                          "yoe_min": 0,  "yoe_max": 1},
    {"title": "Junior Software Engineer",           "level": "junior",    "industry": "software_engineering",
     "required_skills": ["Python", "JavaScript", "Git", "REST APIs", "SQL"],           "yoe_min": 0,  "yoe_max": 2},
    {"title": "Software Engineer II",               "level": "mid",       "industry": "software_engineering",
     "required_skills": ["System Design", "CI/CD", "Docker", "Testing", "SQL"],        "yoe_min": 2,  "yoe_max": 5},
    {"title": "Senior Software Engineer",           "level": "senior",    "industry": "software_engineering",
     "required_skills": ["System Design", "Distributed Systems", "Mentoring",
                         "Code Review", "Performance Optimization"],                   "yoe_min": 5,  "yoe_max": 8},
    {"title": "Staff Software Engineer",            "level": "staff",     "industry": "software_engineering",
     "required_skills": ["Technical Leadership", "Cross-team Collaboration",
                         "Architecture", "Distributed Systems"],                       "yoe_min": 8,  "yoe_max": 12},
    {"title": "Principal Engineer",                 "level": "principal", "industry": "software_engineering",
     "required_skills": ["Org-wide Architecture", "Strategy", "Technical Vision",
                         "Stakeholder Management"],                                    "yoe_min": 12, "yoe_max": 20},
    {"title": "Distinguished Engineer",             "level": "principal", "industry": "software_engineering",
     "required_skills": ["Industry Influence", "Patent Authorship", "Research"],       "yoe_min": 15, "yoe_max": None},
    {"title": "Fellow / VP Engineering",            "level": "vp",        "industry": "software_engineering",
     "required_skills": ["P&L Ownership", "Hiring Strategy", "Board Reporting"],       "yoe_min": 18, "yoe_max": None},
    {"title": "CTO",                                "level": "c-suite",   "industry": "software_engineering",
     "required_skills": ["Technology Vision", "Executive Leadership",
                         "Fundraising", "M&A"],                                        "yoe_min": 20, "yoe_max": None},

    # ─ Frontend Engineering ───────────────────────────────────────────────────
    {"title": "Junior Frontend Developer",          "level": "junior",    "industry": "software_engineering",
     "required_skills": ["HTML", "CSS", "JavaScript", "React"],                        "yoe_min": 0,  "yoe_max": 2},
    {"title": "Frontend Developer",                 "level": "mid",       "industry": "software_engineering",
     "required_skills": ["React", "TypeScript", "Performance", "Accessibility"],       "yoe_min": 2,  "yoe_max": 5},
    {"title": "Senior Frontend Engineer",           "level": "senior",    "industry": "software_engineering",
     "required_skills": ["React", "TypeScript", "Architecture", "Web Vitals"],         "yoe_min": 5,  "yoe_max": 9},
    {"title": "Frontend Architect",                 "level": "staff",     "industry": "software_engineering",
     "required_skills": ["Design Systems", "Micro-frontends", "Leadership"],           "yoe_min": 9,  "yoe_max": None},

    # ─ Backend Engineering ────────────────────────────────────────────────────
    {"title": "Junior Backend Developer",           "level": "junior",    "industry": "software_engineering",
     "required_skills": ["Python", "Node.js", "SQL", "REST APIs"],                     "yoe_min": 0,  "yoe_max": 2},
    {"title": "Backend Developer",                  "level": "mid",       "industry": "software_engineering",
     "required_skills": ["Microservices", "PostgreSQL", "Redis", "Docker"],            "yoe_min": 2,  "yoe_max": 5},
    {"title": "Senior Backend Engineer",            "level": "senior",    "industry": "software_engineering",
     "required_skills": ["Distributed Systems", "Kafka", "System Design", "Security"], "yoe_min": 5,  "yoe_max": 9},

    # ─ DevOps / Platform ──────────────────────────────────────────────────────
    {"title": "DevOps Engineer",                    "level": "mid",       "industry": "software_engineering",
     "required_skills": ["Kubernetes", "Terraform", "CI/CD", "AWS"],                   "yoe_min": 2,  "yoe_max": 6},
    {"title": "Senior DevOps / SRE",                "level": "senior",    "industry": "software_engineering",
     "required_skills": ["SRE", "Chaos Engineering", "On-call", "FinOps"],             "yoe_min": 6,  "yoe_max": 10},
    {"title": "Platform Engineer",                  "level": "staff",     "industry": "software_engineering",
     "required_skills": ["Internal Developer Platform", "Paved-road tooling"],         "yoe_min": 8,  "yoe_max": None},
    {"title": "Director of Engineering",            "level": "director",  "industry": "software_engineering",
     "required_skills": ["Engineering Management", "Roadmap", "Hiring", "OKRs"],       "yoe_min": 10, "yoe_max": None},

    # ─ Data Science ───────────────────────────────────────────────────────────
    {"title": "Data Science Intern",                "level": "intern",    "industry": "data_science",
     "required_skills": ["Python", "Pandas", "Statistics"],                            "yoe_min": 0,  "yoe_max": 1},
    {"title": "Junior Data Scientist",              "level": "junior",    "industry": "data_science",
     "required_skills": ["Python", "SQL", "scikit-learn", "Pandas", "EDA"],            "yoe_min": 0,  "yoe_max": 2},
    {"title": "Data Scientist",                     "level": "mid",       "industry": "data_science",
     "required_skills": ["ML Modeling", "A/B Testing", "SQL", "Feature Engineering"],  "yoe_min": 2,  "yoe_max": 5},
    {"title": "Senior Data Scientist",              "level": "senior",    "industry": "data_science",
     "required_skills": ["Causal Inference", "Deep Learning", "MLOps", "Leadership"],  "yoe_min": 5,  "yoe_max": 9},
    {"title": "Staff Data Scientist",               "level": "staff",     "industry": "data_science",
     "required_skills": ["Research Direction", "Cross-functional Leadership"],         "yoe_min": 9,  "yoe_max": None},
    {"title": "Principal Data Scientist",           "level": "principal", "industry": "data_science",
     "required_skills": ["Company-wide Data Strategy", "Published Research"],          "yoe_min": 12, "yoe_max": None},
    {"title": "ML Engineer",                        "level": "mid",       "industry": "data_science",
     "required_skills": ["PyTorch", "TensorFlow", "MLOps", "Docker", "Feature Store"], "yoe_min": 2,  "yoe_max": 6},
    {"title": "Senior ML Engineer",                 "level": "senior",    "industry": "data_science",
     "required_skills": ["LLMs", "Model Serving", "Distributed Training", "CUDA"],     "yoe_min": 6,  "yoe_max": 10},
    {"title": "ML Platform Engineer",               "level": "staff",     "industry": "data_science",
     "required_skills": ["Feature Store", "Training Platform", "Inference Infra"],     "yoe_min": 8,  "yoe_max": None},
    {"title": "Data Engineer",                      "level": "mid",       "industry": "data_science",
     "required_skills": ["Spark", "Airflow", "dbt", "Data Warehousing", "SQL"],        "yoe_min": 2,  "yoe_max": 6},
    {"title": "Senior Data Engineer",               "level": "senior",    "industry": "data_science",
     "required_skills": ["Real-time Pipelines", "Kafka", "Lakehouse", "Data Contracts"],"yoe_min": 6, "yoe_max": 10},
    {"title": "Head of Data",                       "level": "director",  "industry": "data_science",
     "required_skills": ["Data Strategy", "Governance", "Analytics Leadership"],       "yoe_min": 10, "yoe_max": None},
    {"title": "Chief Data Officer",                 "level": "c-suite",   "industry": "data_science",
     "required_skills": ["Data Monetization", "Regulatory Compliance", "AI Ethics"],   "yoe_min": 15, "yoe_max": None},

    # ─ Product Management ─────────────────────────────────────────────────────
    {"title": "Associate Product Manager",          "level": "junior",    "industry": "product_management",
     "required_skills": ["User Research", "Agile", "Roadmapping", "Analytics"],        "yoe_min": 0,  "yoe_max": 2},
    {"title": "Product Manager",                    "level": "mid",       "industry": "product_management",
     "required_skills": ["PRD Writing", "Stakeholder Management", "OKRs", "A/B Testing"],"yoe_min": 2,"yoe_max": 5},
    {"title": "Senior Product Manager",             "level": "senior",    "industry": "product_management",
     "required_skills": ["Strategy", "Market Analysis", "Revenue Ownership"],          "yoe_min": 5,  "yoe_max": 8},
    {"title": "Group Product Manager",              "level": "staff",     "industry": "product_management",
     "required_skills": ["Team Leadership", "Cross-product Strategy", "P&L"],          "yoe_min": 8,  "yoe_max": 12},
    {"title": "Director of Product",                "level": "director",  "industry": "product_management",
     "required_skills": ["Portfolio Management", "Exec Communication", "Hiring"],      "yoe_min": 10, "yoe_max": None},
    {"title": "VP of Product",                      "level": "vp",        "industry": "product_management",
     "required_skills": ["Product Vision", "Market Positioning", "Board Reporting"],   "yoe_min": 14, "yoe_max": None},
    {"title": "Chief Product Officer",              "level": "c-suite",   "industry": "product_management",
     "required_skills": ["Corporate Strategy", "M&A", "Investor Relations"],           "yoe_min": 18, "yoe_max": None},

    # ─ Finance / Quant ────────────────────────────────────────────────────────
    {"title": "Finance Analyst",                    "level": "junior",    "industry": "finance",
     "required_skills": ["Excel", "Financial Modeling", "Accounting", "SQL"],          "yoe_min": 0,  "yoe_max": 3},
    {"title": "Senior Financial Analyst",           "level": "mid",       "industry": "finance",
     "required_skills": ["DCF", "Valuation", "Python", "Power BI"],                   "yoe_min": 3,  "yoe_max": 6},
    {"title": "Finance Manager",                    "level": "senior",    "industry": "finance",
     "required_skills": ["FP&A", "Budget Management", "Business Partnering"],          "yoe_min": 6,  "yoe_max": 10},
    {"title": "Director of Finance",                "level": "director",  "industry": "finance",
     "required_skills": ["Strategic Finance", "Capital Allocation", "M&A"],            "yoe_min": 10, "yoe_max": None},
    {"title": "CFO",                                "level": "c-suite",   "industry": "finance",
     "required_skills": ["Treasury", "Investor Relations", "GAAP", "SOX Compliance"],  "yoe_min": 18, "yoe_max": None},
    {"title": "Quantitative Analyst",               "level": "mid",       "industry": "finance",
     "required_skills": ["Python", "Stochastic Calculus", "C++", "Risk Modeling"],     "yoe_min": 2,  "yoe_max": 6},
    {"title": "Senior Quantitative Analyst",        "level": "senior",    "industry": "finance",
     "required_skills": ["Machine Learning", "Time Series", "Alpha Generation"],       "yoe_min": 6,  "yoe_max": 10},
    {"title": "Quantitative Researcher",            "level": "staff",     "industry": "finance",
     "required_skills": ["Statistical Arbitrage", "NLP for Finance", "Backtesting"],   "yoe_min": 8,  "yoe_max": None},
    {"title": "Portfolio Manager",                  "level": "principal", "industry": "finance",
     "required_skills": ["Portfolio Construction", "Risk Management", "Derivatives"],  "yoe_min": 12, "yoe_max": None},

    # ─ Consulting ─────────────────────────────────────────────────────────────
    {"title": "Business Analyst (Consulting)",      "level": "junior",    "industry": "consulting",
     "required_skills": ["PowerPoint", "Problem Structuring", "Excel", "Stakeholder Management"],"yoe_min": 0,"yoe_max": 2},
    {"title": "Consultant",                         "level": "mid",       "industry": "consulting",
     "required_skills": ["Project Management", "Client Management", "Workshop Facilitation"],"yoe_min": 2,"yoe_max": 4},
    {"title": "Senior Consultant",                  "level": "senior",    "industry": "consulting",
     "required_skills": ["Proposal Writing", "Business Development", "Team Leadership"],"yoe_min": 4,"yoe_max": 7},
    {"title": "Manager (Consulting)",               "level": "staff",     "industry": "consulting",
     "required_skills": ["Engagement Management", "P&L Responsibility", "Mentoring"], "yoe_min": 7,  "yoe_max": 10},
    {"title": "Principal (Consulting)",             "level": "principal", "industry": "consulting",
     "required_skills": ["Practice Building", "Thought Leadership", "Client Acquisition"],"yoe_min": 10,"yoe_max": None},
    {"title": "Partner",                            "level": "director",  "industry": "consulting",
     "required_skills": ["Revenue Generation", "Industry Expertise", "Equity"],        "yoe_min": 12, "yoe_max": None},

    # ─ Marketing ─────────────────────────────────────────────────────────────
    {"title": "Marketing Coordinator",              "level": "junior",    "industry": "marketing",
     "required_skills": ["Canva", "Social Media", "Email Marketing", "Analytics"],     "yoe_min": 0,  "yoe_max": 2},
    {"title": "Marketing Manager",                  "level": "mid",       "industry": "marketing",
     "required_skills": ["SEO", "SEM", "Campaign Management", "Google Analytics"],     "yoe_min": 2,  "yoe_max": 5},
    {"title": "Senior Marketing Manager",           "level": "senior",    "industry": "marketing",
     "required_skills": ["Growth Strategy", "Content Marketing", "Brand Positioning"], "yoe_min": 5,  "yoe_max": 8},
    {"title": "Head of Marketing",                  "level": "director",  "industry": "marketing",
     "required_skills": ["Budget Ownership", "Agency Management", "GTM Strategy"],     "yoe_min": 8,  "yoe_max": None},
    {"title": "VP of Marketing",                    "level": "vp",        "industry": "marketing",
     "required_skills": ["Brand Strategy", "Demand Generation", "Board Reporting"],    "yoe_min": 12, "yoe_max": None},
    {"title": "CMO",                                "level": "c-suite",   "industry": "marketing",
     "required_skills": ["Corporate Communications", "Investor Relations", "M&A"],     "yoe_min": 15, "yoe_max": None},
    {"title": "Growth Marketing Manager",           "level": "mid",       "industry": "marketing",
     "required_skills": ["A/B Testing", "SQL", "Paid Acquisition", "Retention"],       "yoe_min": 2,  "yoe_max": 6},
    {"title": "Product Marketing Manager",          "level": "mid",       "industry": "marketing",
     "required_skills": ["Positioning", "Competitive Analysis", "Launch Planning"],    "yoe_min": 3,  "yoe_max": 7},
    {"title": "Senior Product Marketing Manager",   "level": "senior",    "industry": "marketing",
     "required_skills": ["GTM Ownership", "Sales Enablement", "Market Research"],      "yoe_min": 7,  "yoe_max": None},

    # ─ Design ─────────────────────────────────────────────────────────────────
    {"title": "Junior UX Designer",                 "level": "junior",    "industry": "design",
     "required_skills": ["Figma", "User Research", "Wireframing", "Prototyping"],      "yoe_min": 0,  "yoe_max": 2},
    {"title": "UX Designer",                        "level": "mid",       "industry": "design",
     "required_skills": ["Design Systems", "Usability Testing", "Information Architecture"],"yoe_min": 2,"yoe_max": 5},
    {"title": "Senior UX Designer",                 "level": "senior",    "industry": "design",
     "required_skills": ["Strategic Design", "Design Leadership", "Accessibility"],    "yoe_min": 5,  "yoe_max": 9},
    {"title": "Lead UX Designer",                   "level": "staff",     "industry": "design",
     "required_skills": ["Design Ops", "Team Management", "Design Critique"],          "yoe_min": 9,  "yoe_max": None},
    {"title": "Head of Design / Design Director",   "level": "director",  "industry": "design",
     "required_skills": ["Product Vision", "Brand Consistency", "Cross-functional Leadership"],"yoe_min": 12,"yoe_max": None},
]

# ── Transition edges ──────────────────────────────────────────────────────────
# (from_title, to_title, avg_years, difficulty)

TRANSITIONS: list[tuple[str, str, float, str]] = [
    # Software Engineering ladder
    ("Software Engineering Intern",     "Junior Software Engineer",        0.5, "easy"),
    ("Junior Software Engineer",        "Software Engineer II",            2.5, "moderate"),
    ("Software Engineer II",            "Senior Software Engineer",        3.0, "moderate"),
    ("Senior Software Engineer",        "Staff Software Engineer",         3.5, "hard"),
    ("Staff Software Engineer",         "Principal Engineer",              4.0, "hard"),
    ("Principal Engineer",              "Distinguished Engineer",          5.0, "hard"),
    ("Distinguished Engineer",          "Fellow / VP Engineering",         4.0, "hard"),
    ("Fellow / VP Engineering",         "CTO",                             4.0, "hard"),
    # Frontend ladder
    ("Junior Frontend Developer",       "Frontend Developer",              2.5, "moderate"),
    ("Frontend Developer",              "Senior Frontend Engineer",        3.0, "moderate"),
    ("Senior Frontend Engineer",        "Frontend Architect",              3.5, "hard"),
    # Cross-track: Frontend → general SWE
    ("Senior Frontend Engineer",        "Senior Software Engineer",        1.0, "moderate"),
    ("Frontend Architect",              "Staff Software Engineer",         1.5, "moderate"),
    # Backend ladder
    ("Junior Backend Developer",        "Backend Developer",               2.5, "moderate"),
    ("Backend Developer",               "Senior Backend Engineer",         3.0, "moderate"),
    ("Senior Backend Engineer",         "Senior Software Engineer",        1.0, "easy"),
    # DevOps ladder
    ("DevOps Engineer",                 "Senior DevOps / SRE",             3.0, "moderate"),
    ("Senior DevOps / SRE",             "Platform Engineer",               2.5, "hard"),
    ("Platform Engineer",               "Director of Engineering",         3.0, "hard"),
    ("Senior Software Engineer",        "Director of Engineering",         4.0, "hard"),
    ("Staff Software Engineer",         "Director of Engineering",         2.0, "moderate"),
    # Data Science ladder
    ("Data Science Intern",             "Junior Data Scientist",            0.5, "easy"),
    ("Junior Data Scientist",           "Data Scientist",                  2.5, "moderate"),
    ("Data Scientist",                  "Senior Data Scientist",           3.0, "moderate"),
    ("Senior Data Scientist",           "Staff Data Scientist",            3.5, "hard"),
    ("Staff Data Scientist",            "Principal Data Scientist",        4.0, "hard"),
    ("Principal Data Scientist",        "Chief Data Officer",              5.0, "hard"),
    # ML ladder
    ("Data Scientist",                  "ML Engineer",                     1.5, "moderate"),
    ("ML Engineer",                     "Senior ML Engineer",              3.0, "moderate"),
    ("Senior ML Engineer",              "ML Platform Engineer",            2.5, "hard"),
    # Data Engineering
    ("Junior Data Scientist",           "Data Engineer",                   1.5, "moderate"),
    ("Data Engineer",                   "Senior Data Engineer",            3.0, "moderate"),
    ("Senior Data Engineer",            "Head of Data",                    4.0, "hard"),
    ("Principal Data Scientist",        "Head of Data",                    2.0, "moderate"),
    ("Head of Data",                    "Chief Data Officer",              5.0, "hard"),
    # PM ladder
    ("Associate Product Manager",       "Product Manager",                 2.0, "moderate"),
    ("Product Manager",                 "Senior Product Manager",          3.0, "moderate"),
    ("Senior Product Manager",          "Group Product Manager",           3.0, "hard"),
    ("Group Product Manager",           "Director of Product",             2.5, "hard"),
    ("Director of Product",             "VP of Product",                   3.0, "hard"),
    ("VP of Product",                   "Chief Product Officer",           4.0, "hard"),
    # Finance ladder
    ("Finance Analyst",                 "Senior Financial Analyst",        3.0, "moderate"),
    ("Senior Financial Analyst",        "Finance Manager",                 3.0, "moderate"),
    ("Finance Manager",                 "Director of Finance",             4.0, "hard"),
    ("Director of Finance",             "CFO",                             6.0, "hard"),
    # Quant ladder
    ("Quantitative Analyst",            "Senior Quantitative Analyst",     3.0, "moderate"),
    ("Senior Quantitative Analyst",     "Quantitative Researcher",         3.0, "hard"),
    ("Quantitative Researcher",         "Portfolio Manager",               4.0, "hard"),
    # Consulting ladder
    ("Business Analyst (Consulting)",   "Consultant",                      2.0, "moderate"),
    ("Consultant",                      "Senior Consultant",               2.5, "moderate"),
    ("Senior Consultant",               "Manager (Consulting)",            3.0, "moderate"),
    ("Manager (Consulting)",            "Principal (Consulting)",          3.0, "hard"),
    ("Principal (Consulting)",          "Partner",                         4.0, "hard"),
    # Marketing ladder
    ("Marketing Coordinator",           "Marketing Manager",               2.5, "moderate"),
    ("Marketing Manager",               "Senior Marketing Manager",        3.0, "moderate"),
    ("Senior Marketing Manager",        "Head of Marketing",               3.5, "hard"),
    ("Head of Marketing",               "VP of Marketing",                 4.0, "hard"),
    ("VP of Marketing",                 "CMO",                             5.0, "hard"),
    ("Growth Marketing Manager",        "Head of Marketing",               4.0, "hard"),
    ("Product Marketing Manager",       "Senior Product Marketing Manager",3.0, "moderate"),
    # Design ladder
    ("Junior UX Designer",              "UX Designer",                     2.5, "moderate"),
    ("UX Designer",                     "Senior UX Designer",              3.0, "moderate"),
    ("Senior UX Designer",              "Lead UX Designer",                3.5, "hard"),
    ("Lead UX Designer",                "Head of Design / Design Director",3.0, "hard"),
    # Cross-functional pivots
    ("Senior Software Engineer",        "Senior Product Manager",          2.0, "hard"),
    ("Data Scientist",                  "Product Manager",                 2.0, "hard"),
    ("Senior Data Scientist",           "ML Engineer",                     1.0, "moderate"),
    ("ML Engineer",                     "Data Scientist",                  1.0, "easy"),
    ("Finance Analyst",                 "Quantitative Analyst",            2.0, "hard"),
    ("Software Engineer II",            "DevOps Engineer",                 1.5, "moderate"),
    ("Backend Developer",               "DevOps Engineer",                 1.5, "moderate"),
]
