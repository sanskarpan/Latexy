from app.services.ats_resume_schema import from_structured_resume, partial_date


def test_partial_dates_preserve_observed_precision_without_fabrication():
    year = partial_date("2022")
    month = partial_date("Jan 2023")
    day = partial_date("2024-05-17")
    current = partial_date("", current=True)

    assert (year.found_year, year.found_month, year.found_day) == (True, False, False)
    assert (month.found_year, month.found_month, month.found_day) == (True, True, False)
    assert (day.found_year, day.found_month, day.found_day) == (True, True, True)
    assert current.value == "Present"
    assert current.is_current is True


def test_structured_projection_matches_convergent_ats_core():
    profile = from_structured_resume(
        {
            "basics": {
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "phone": "+44 20 7946 0958",
                "location": "London, England, United Kingdom",
                "linkedin": "linkedin.com/in/ada",
                "website": "ada.example",
            },
            "experience": [
                {
                    "company": "Analytical Engines Ltd",
                    "title": "Principal Engineer",
                    "start_date": "Mar 2020",
                    "end_date": "",
                    "current": True,
                    "summary": "Led the platform programme.",
                    "bullets": ["Built Python forecasting services."],
                }
            ],
            "education": [
                {
                    "institution": "University of London",
                    "degree": "BSc",
                    "field": "Mathematics",
                    "start_date": "2012",
                    "end_date": "2015",
                }
            ],
            "skills": [
                {"name": "Core", "keywords": ["Python", "SQL"]},
                {"name": "Other", "keywords": ["python", "Leadership"]},
            ],
        }
    )

    assert profile.identity.model_dump() == {
        "given_name": "Ada",
        "family_name": "Lovelace",
    }
    assert profile.contact.model_dump() == {
        "email": "ada@example.com",
        "phone": "+44 20 7946 0958",
        "city": "London",
        "region": "England",
        "country": "United Kingdom",
    }
    assert profile.links.linkedin == "linkedin.com/in/ada"
    assert profile.links.personal_site == "ada.example"
    assert profile.work[0].employer == "Analytical Engines Ltd"
    assert profile.work[0].job_title == "Principal Engineer"
    assert profile.work[0].end_date.is_current is True
    assert "Python forecasting" in profile.work[0].description
    assert profile.education[0].field == "Mathematics"
    assert profile.skills == ["Python", "SQL", "Leadership"]
