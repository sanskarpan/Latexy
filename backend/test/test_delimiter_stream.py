from app.workers.delimiter_stream import DelimitedStreamFilter


def test_filter_hides_prose_and_markers_split_across_chunks():
    stream = DelimitedStreamFilter()
    chunks = [
        "Here is your document:\n<<<LAT",
        "EX>>>\\documentclass{article}\n\\begin{doc",
        "ument}Hello\\end{document}<<<END_LAT",
        "EX>>>ignored",
    ]

    assert "".join(stream.feed(chunk) for chunk in chunks) == (
        "\\documentclass{article}\n\\begin{document}Hello\\end{document}"
    )


def test_filter_emits_nothing_without_start_marker():
    stream = DelimitedStreamFilter()

    assert stream.feed("ordinary model prose") == ""
