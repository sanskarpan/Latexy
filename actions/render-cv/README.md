# Render a CV with Latexy

The repository-root `action.yml` is a dependency-free Node 24 Action that submits
a checked-in `.tex` file to the Latexy developer API, polls the authoritative job
state, downloads the PDF, validates its header, and atomically writes it inside
the runner workspace.

```yaml
name: Render CV
on:
  push:
    paths: ['resume.tex']

permissions:
  contents: read

jobs:
  render:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - id: cv
        uses: sanskarpan/Latexy@v1
        with:
          api-key: ${{ secrets.LATEXY_API_KEY }}
          source: resume.tex
          output: artifacts/resume.pdf
          compiler: lualatex
      - uses: actions/upload-artifact@v6
        with:
          name: resume
          path: ${{ steps.cv.outputs.pdf-path }}
```

Create the secret in Latexy's developer portal using a key with both `compile`
and `export` scopes. The Action masks the key, never places it on a command line,
requires HTTPS except for loopback tests, constrains source/output paths to
`GITHUB_WORKSPACE`, limits source size to the API contract, waits at most 180
seconds by default, and never replaces an existing output with an invalid or
partial download.
