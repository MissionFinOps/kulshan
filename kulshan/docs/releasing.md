# Release process

Version 0.7.0 uses the release date **2026-10-17** (Mission, BC). The version module and changelog carry the same date. Public availability must be verified through the successful tag workflow, GitHub Release and PyPI; a local build alone is not publication.

Python 3.11+ is required. CI tests 3.11, 3.12 and 3.13 independently (`fail-fast: false`) and reports skip reasons. Use Python 3.11+ for `python -m pip install kulshan` or `python -m pip install -e './kulshan[dev]'` from the repository root. The optional MCP extra supports SDK 1.x, not 2.x.

For each release, obtain authorization, finalize matching version and actual date metadata in a release PR, and merge it only after CI passes. Verify the resulting approved master commit and its successful CI before tagging. From `kulshan/`, run `python scripts/validate_release.py --tag v0.7.0`. Recheck GitHub tags and PyPI version availability immediately before creating an annotated tag. Do not use an old availability check as authorization or proof that the version is still free.

Only pushing a `v*` tag triggers `publish.yml`. Its validation and reusable CI must succeed before trusted PyPI publishing and GitHub Release creation. Branch pushes and PRs run CI but do not authorize publication. Tag creation, tag push and publication require explicit authorization. Version 0.7.0 has that authorization; future releases require their own.

The Ruff baseline now targets Python 3.11. Its migration adds exactly 86 pre-existing detections enabled by that target: UP017 (71), UP042 (8), B905 (5), UP035 (1), UP045 (1). No new source violations were accepted; the baseline total is 2,404, with 2,399 current residual violations. This records existing debt without a repository-wide cleanup.
