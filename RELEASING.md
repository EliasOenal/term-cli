# Releasing term-cli

term-cli follows [Semantic Versioning](https://semver.org/). `VERSION` is the
source of truth, and the standalone executables contain synchronized embedded
versions so that they can report their version without repository files.

Git tags named `vX.Y.Z` identify immutable releases. GitHub Releases contain
the release notes and downloadable artifacts; no separate changelog is
maintained.

## Version changes

- `MAJOR`: incompatible CLI or behavior changes.
- `MINOR`: backward-compatible commands and features.
- `PATCH`: backward-compatible fixes.

Pre-release versions such as `1.1.0-rc.1` are supported and become GitHub
prereleases.

## Release steps

1. Ensure all intended changes are on `main` and the worktree is clean.
2. Run `./release.sh X.Y.Z` without a leading `v`.
3. If it creates a version commit, push `main` and wait for the full Tests
   workflow to pass, then run the same release command again.
4. Review the annotated tag and run the tag push command printed by the script.
5. Confirm the `Release` GitHub Actions workflow creates the GitHub Release.
6. Smoke-test the published installer and `term-cli --version`.

The release script validates SemVer, synchronizes the embedded versions, runs
Pyright and the full test suite, and creates a version commit when needed. It
only creates the annotated tag after that commit has been pushed separately.
It deliberately does not push.

The GitHub workflow verifies the tag and versions, reruns all checks, generates
release notes, and publishes pinned standalone files, a source bundle, and
SHA-256 checksums. Its published `install.sh` downloads from the matching tag,
not from the mutable `main` branch.
