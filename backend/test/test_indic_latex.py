from app.services.indic_latex import configure_devanagari_latex, uses_devanagari


def test_only_declared_devanagari_language_codes_use_hosted_stack():
    assert uses_devanagari(" hi ")
    assert uses_devanagari("MR")
    assert not uses_devanagari("ta")
    assert not uses_devanagari("fr")


def test_devanagari_configuration_replaces_conflicting_preamble():
    source = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[french]{babel}
\usepackage{geometry,inputenc}
\begin{document}
अनुभव
\end{document}"""

    configured = configure_devanagari_latex(source)

    assert r"\usepackage{inputenc}" not in configured
    assert r"\usepackage[utf8]{inputenc}" not in configured
    assert r"\usepackage[T1]{fontenc}" not in configured
    assert r"\usepackage[french]{babel}" not in configured
    assert configured.count(r"\usepackage{fontspec}") == 1
    assert r"\usepackage{geometry}" in configured
    assert "geometry,inputenc" not in configured
    assert r"\babelprovide[onchar=ids fonts]{english}" in configured
    assert r"\renewcommand{\bfdefault}{b}" in configured
    assert r"\renewcommand{\labelitemi}{\foreignlanguage{english}{\textbullet}}" in configured
    assert r'\catcode"2022=\active' in configured
    assert r"\babelfont[english]{rm}{Latin Modern Roman}" in configured
    assert "Renderer=HarfBuzz,Script=Devanagari" in configured
    assert "BoldFont={Noto Sans Devanagari Bold}" in configured
    assert "ItalicFont={Noto Sans Devanagari}" in configured
    assert "ItalicFeatures={FakeSlant=0.15}" in configured
    assert "BoldItalicFont={Noto Sans Devanagari Bold}" in configured
    assert "अनुभव" in configured


def test_devanagari_configuration_rejects_incomplete_model_output():
    try:
        configure_devanagari_latex("केवल अनुवादित पाठ")
    except ValueError as exc:
        assert "document class" in str(exc)
    else:  # pragma: no cover - makes the failure message explicit
        raise AssertionError("Incomplete translation was accepted")
