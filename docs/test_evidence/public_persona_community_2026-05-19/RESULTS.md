# Public Persona Community Test Results

Date: 2026-05-19

## Result

All required automated checks passed.

| Check | Evidence File | Result |
| --- | --- | --- |
| Environment and deployment entrypoint inventory | `00_environment.txt` | Captured |
| Backend/unit/integration tests | `01_pytest.log` | `12 passed` |
| Ruff lint | `02_ruff.log` | Passed |
| Frontend TypeScript/Vite build | `03_frontend_build.log` | Passed |
| Windows deploy PowerShell AST parse | `04_deploy_script_ast.log` | 0 parse errors for 4 scripts |
| Live public catalog API shape | `05_public_catalog_api.json` | Returned `query/sort/offset/limit/total/results` |
| Exit code summary | `06_exit_codes.txt` | All exit codes 0 |
| Synthetic public-persona policy demonstration | `07_public_persona_policy_demo.json` | Ready public listed; private blocked; citations redacted |

## Notes For Report

- The local live API had no already-published ready user personas, so `05_public_catalog_api.json` correctly shows `total: 0` while preserving the public catalog response shape.
- `07_public_persona_policy_demo.json` creates an isolated temporary metadata store and proves the functional boundary with controlled data:
  - only one ready public persona is listed,
  - a private ready persona is blocked for a non-owner,
  - a non-owner sees zero Material Lens documents for a public user persona,
  - citation title, path, preview, and selected chunk id are redacted to public labels.
- `04_deploy_script_ast.log` proves the branch contains parseable PowerShell entrypoints for:
  - `bootstrap.ps1`,
  - `install.ps1`,
  - `scripts/deploy/windows_local_gui_deploy.ps1`,
  - `scripts/deploy/windows_uninstall.ps1`.

## Exact Commands

```powershell
uv run pytest -q
uv run ruff check app tests scripts
npm run build
```

Deployment AST validation used:

```powershell
[System.Management.Automation.Language.Parser]::ParseFile(...)
```
