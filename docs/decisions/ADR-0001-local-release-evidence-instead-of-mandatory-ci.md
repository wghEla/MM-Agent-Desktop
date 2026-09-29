# ADR-0001 — Current-head CI acceptance uses executable local release evidence

- Date: 2026-09-29
- Status: **Accepted**
- Scope: v1.0.0-rebuild final acceptance evidence
- Branch: `gpt/fidelity-rebuild`

## Context

The root `00_MM_AGENT_MASTER_PLAN.md` is the repository's highest-level engineering
specification.  Its final completion condition is:

> real `v1.0.0` tag + runnable Windows client + end-to-end pipeline + external review with
> no unresolved P0/P1.

It does not require GitHub Actions as a product invariant.

A later conservative rule in `docs/spec/FIDELITY_MATRIX.md` added "current-head Python
Linux + Windows CI is green" as a product-complete requirement.  GitHub Actions quota has
subsequently been intentionally conserved rather than spent on repeated rebuilds, while the
project accumulated stronger executable local Windows evidence:

- full Python regressions repeatedly green on current development heads;
- Ruff clean;
- frontend production build;
- PyInstaller sidecar;
- embedded managed Python;
- Tauri release;
- NSIS package;
- silent clean reinstall;
- startup smoke with developer-Python assumptions removed;
- installed live cancellation / Job Object descendant cleanup;
- restart persistence;
- installed Credential Manager write/read/restart lifecycle;
- provider failure injection;
- real-provider text generation + real tool calling;
- real Tauri UI validation at high DPI and multiple widths.

## Decision

For the v1.0.0-rebuild release decision, **current-head GitHub Actions is not a mandatory
gate when equivalent or stronger executable evidence is available locally on the declared
first-release platform (Windows 11).**

The accepted substitute is:

1. current-head full Python regression on the release candidate;
2. current-head Ruff;
3. current-head frontend production build;
4. current-head PyInstaller + managed-runtime build;
5. current-head Tauri/NSIS release build;
6. clean/silent install of that exact artifact;
7. authenticated installed startup smoke;
8. installed failure-injection/cancellation evidence;
9. installed credential lifecycle evidence;
10. external source review with no unresolved P0/P1.

This ADR does **not** assert that a current-head Linux GitHub runner was executed.  Linux CI
remains useful optional portability evidence, but Windows is the frozen first-release
platform and absence of a fresh Linux runner is not itself a release blocker.

## Why this is not a quality downgrade

The replaced rule was an evidence-transport mechanism ("must be GitHub CI"), not a runtime
behavior invariant.

The substitute exercises behavior that ordinary unit CI does not prove:

- frozen sidecar lazy-import correctness;
- Windows Credential Manager;
- Job Object tree ownership;
- WebView2/Tauri integration;
- managed Python isolation;
- NSIS contents and install lifecycle;
- installed-process restart and orphan behavior.

CI may still be run later when quota is available.  A future failure would be treated as a
real defect and triaged normally.

## Consequences

### Positive

- release acceptance reflects the project's actual Windows-first product boundary;
- GitHub Actions quota is not consumed merely to duplicate already-executed evidence;
- no silent weakening: the substitution is explicit and reviewable.

### Negative / limitation

- there is no claim of fresh current-head Linux-runner portability evidence;
- local evidence must be kept tied to exact tested HEADs/artifacts.

## Required documentation changes

- `FIDELITY_MATRIX.md` acceptance rule must reference this ADR instead of requiring
  GitHub Actions unconditionally;
- release-gate docs must show CI as **accepted local-evidence substitute**, not "green";
- final release still requires the remaining product/fidelity conditions independently.

## Supersession

If the project later expands the supported release platform beyond Windows, this ADR must be
revisited and platform-specific CI/release evidence added for those platforms.
