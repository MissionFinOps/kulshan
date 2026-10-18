# Preparing v0.7.0

The package version is 0.7.0, but the release is **unreleased**. Its date is deliberately blank in `kulshan/src/kulshan/__version__.py`, and the changelog heading is `0.7.0 - Unreleased`. The release validator must reject this draft state. No publication date is implied by package installation or CI builds.

Python 3.11+ is required. CI tests 3.11, 3.12 and 3.13 independently (`fail-fast: false`) and reports skip reasons. Use Python 3.11+ for `python -m pip install kulshan` or `python -m pip install -e './kulshan[dev]'` from the repository root. The optional MCP extra supports SDK 1.x, not 2.x.

After separate release authorization and merge to master, verify the approved master commit and set the actual release date in both the version module and changelog. From `kulshan/`, run `python scripts/validate_release.py --tag v0.7.0`. Recheck GitHub tags and PyPI version availability immediately before creating an annotated tag. Do not use an old availability check as authorization or proof that the version is still free.

Only pushing a `v*` tag triggers `publish.yml`. Its validation and reusable CI must succeed before trusted PyPI publishing and GitHub Release creation. Branch pushes and PRs run CI but do not authorize publication. Tag creation, tag push and publication are separate, later actions requiring explicit authorization.

The Ruff baseline now targets Python 3.11. Its migration adds exactly 86 pre-existing detections enabled by that target: UP017 (71), UP042 (8), B905 (5), UP035 (1), UP045 (1). No new source violations were accepted; the baseline total is 2,404, with 2,399 current residual violations. This records existing debt without a repository-wide cleanup.
