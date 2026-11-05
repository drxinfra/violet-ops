# Changelog

## 1.0.0 — 2026-11-05

First public release.

- Three variants: **Violet Ops** (main), **Violet Ops Graphite** (same colors on a neutral background),
  **Violet Ops Calm** (muted palette).
- Ansible: module, documented module parameter, task keyword and other keys get distinct colors
  (semantic tokens of the Red Hat Ansible extension, scoped to the `ansible` language only).
- Jinja: `{{ }}` and `{% %}` delimiters, variables, filters and tests.
- Helm: template actions, `.Values` and `$variables`, Sprig functions, no bold spill over whole `{{ … }}`.
- Jenkins: a small injection grammar marks declarative pipeline blocks (`pipeline`, `stages`, `steps`, `post`…),
  common steps (`sh`, `checkout`, `withCredentials`…) and `env.` / `params.` / `currentBuild.`.
- SQL table aliases and columns, Markdown headings by level, Error Lens colors, bracket pair colors.
- Every code color is at least 7:1 (WCAG 2) against the background; neighbouring roles differ by ΔE ≥ 0.06 in OKLab.
