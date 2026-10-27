# WK-3D F3A — Real Office Environment · Technical implementation

**Reference:** `nikolicslobodan007-dot/mm-persona-os`, `main` SHA `cbb73908a1b205ca4289a9777e0fa289cfa45cf5` (2026-10-27).  **Scope:** *front-end/static only*. The authenticated route `/console/office/3d`, django auth, Office V1.2 API, backend models and orchestration remain unchanged.

## Delivered

Five **actual GLB 2.0 model files**, generated with the included deterministic Python source (`tools/office_3d_f3a/build_models.py`):

| GLB model | Contents | Usage |
|---|---|---|
| `f3a-room.glb` | Oak plank flooring, architectural shell, window frames, glass surfaces, wall accent panel, perimeter trims and rugs | One room |
| `f3a-desk.glb` | Wooden desk, steel legs, two screens, keyboard, cup | Five GPU draw calls from one uploaded model |
| `f3a-chair.glb` | Upholstered swivel chair with base and armrests | Five instances |
| `f3a-plant.glb` | Low-polygon ficus and pot | Two instances |
| `f3a-shelf.glb` | Wooden bookshelf and books | One instance |

The scene is around **7,468 triangles** with five complete workstations and furniture. The model generator requires `numpy` and `trimesh` only when regenerating assets; neither is required on the Django server or in the visitor's browser.

## Architecture

- `console/static/console/office-3d-f3a.js` contains a *purpose-limited GLB 2.0 loader* and WebGL shader. It accepts only pre-baked, colored, static triangle geometry (`POSITION`, `NORMAL`, `COLOR_0`) authored in this package. This is **not** a general glTF viewer.
- `console/static/console/office-3d.js` continues to control identity, status, authorized API fetching, labels, selection, navigation and camera. The added F3A option replaces geometry only when **all five** static assets have loaded and passed format checks.
- `console/templates/console/office_3d.html` enumerates Django `{% static %}`-resolved GLB URLs, compatible with static fingerprinting. Loading is `same-origin`, with strict path whitelisting (no CDN, credentials, query strings, inline dynamic scripts or new API endpoints).
- If F3A model loading fails, the existing WebGL cubes are retained. If WebGL context creation fails, the existing Canvas 2D fallback and DOM agent list are retained.
- For now, agents are **simple colored presence markers** and linked DOM labels; they are not full 3D characters, are **not** animated, and must never imply confirmed RUNNING activity. Agent-specific 3D avatars are reserved for F3B.

## Integration

From a clean checkout of the exact SHA above (or compatible later main after a review):

```bash
git checkout -b feature/wk-3d-f3a-real-office
git apply --check WK_3D_F3A_Real_Office.patch
git apply WK_3D_F3A_Real_Office.patch
node --test tests/office_3d_f3a.test.cjs
node --check console/static/console/office-3d-f3a.js
node --check console/static/console/office-3d.js
python tools/canon_lint.py
ruff check .
python manage.py makemigrations --check --dry-run
python -m pytest
```

**Crucial test:** log in on staging with the existing Django session and TOTP, open `/console/office/3d` on Chrome/Firefox with WebGL, and confirm that the scene badge switches to `3D modeli · F3A`. Confirm five desks/chairs, selection and camera, staticfiles after collectstatic, no CSP violations, and that disabling WebGL restores the existing 2D scene.

## Acceptance gates

1. Verify local GLB loading with HTTP 200 and same-origin URLs (including ManifestStaticFilesStorage fingerprinted filenames).
2. Verify graphics: five desks and chairs, both plants and shelf, correct z-buffer, orbit camera, zoom, responsive layout, and acceptable frame rate on a normal workstation. Take real browser screenshots.
3. Verify business semantics: only five visible agents chosen from V1.2 API, active/ready does not imply working, selecting a workplace opens real inspector data; filters and pagination clear stale selections.
4. Check security: TOTP/session, `script-src 'self'`, no new API/data writes, no external assets, no untrusted generated 3D code execution.
5. Run the four existing project CI gates (canon_lint, ruff, Django migrations, pytest). No merge without explicit approval.

## Limits and next steps

This is a **parametric low-poly GLB pilot**, not cinematic 3D, no skeletal characters and no 3DCodeVerse inference. It establishes a modular 3D asset loading contract and richer real geometry than procedural WebGL cubes. After real browser validation proceed with F3B: licensed stylized humanoid GLB avatars, preferably provided by an approved art pipeline. The 3DCodeVerse-based **offline asset-worker** should be evaluated later in a sandbox with geometry/render/license checks before approved output is added as static GLB.

**Asset provenance:** All five models here are newly, deterministically authored by the included Python generator; the published 3DCodeVerse datasets have not been used.
