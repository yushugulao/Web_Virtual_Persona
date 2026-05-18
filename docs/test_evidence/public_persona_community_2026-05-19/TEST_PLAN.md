# Public Persona Community Test Plan

Date: 2026-05-19

## Scope

This evidence set validates the login-only community sharing feature for public user personas and confirms that the branch still contains the Windows graphical quick deployment path.

## Functional Claims

1. Ready user personas can be published and unpublished.
2. Draft, building, or failed personas cannot be publicly published and return a clear user-facing error.
3. The public catalog lists only `is_public=true` and `runtime_status=ready` user personas, with pagination and sorting shape.
4. Public catalog cards expose only safe card fields, not owner ids or source paths.
5. Non-owners can chat with ready public user personas through the resolved persona path.
6. Non-owners cannot access private, draft, building, or failed user personas.
7. Non-owner material access for public user personas hides Material Lens documents, raw paths, previews, and source paths.
8. Non-owner public chat and retrieval responses redact citations and retrieval trace candidates.
9. Owners retain their own management-facing detail fields.
10. The creation dialog checks DeepSeek key configuration before starting a build.
11. The frontend public directory renders the new public catalog flow and builds successfully.
12. The branch includes the Windows graphical quick deploy scripts, uninstaller flow, OCR/DeepSeek/SMTP configuration, and deployment profiles.

## Automated Coverage

- `tests/test_public_persona_community.py`
  - publish/unpublish readiness rules
  - clear publish endpoint error for non-ready personas
  - public catalog list filtering and endpoint pagination shape
  - non-owner detail redaction
  - material isolation for public/private user personas
  - retrieval/chat citation and trace redaction

- `tests/test_deployment_assets.py`
  - required quick deployment entrypoints exist
  - bootstrap/install scripts target the graphical deployer
  - user-facing GUI text and success/uninstall flow exist
  - runtime configuration keys are written by the GUI deployer

## Evidence Commands

```powershell
uv run pytest -q
uv run ruff check app tests scripts
npm run build
```

Additional deployment evidence:

```powershell
# Parse Windows PowerShell scripts with the PowerShell AST parser.
# Confirm bootstrap.ps1, install.ps1, windows_local_gui_deploy.ps1, and windows_uninstall.ps1 have zero parse errors.
```

Additional API evidence:

```powershell
# Query /persona-catalog/public on a running local backend.
# The response must have query/sort/offset/limit/total/results shape.
```
