# PR-B6 — Executive Office: high-resolution 2.5D visual pilot

**Target:** Web Korporacija Virtual Office, Django frontend only. **Based on `main` commit `c4251b29298576d93dd40719c43ef7e66b16cec2`** (VO V1.4B.5).

## Deliverables

- Five **original local PNG assets**, rasterized from reproducible vector sources (two room backgrounds, one transparent foreground, two transparent business-character sprites).
- `tools/office_v14b/src/executive-v6.mjs`: strictly allowlisted same-origin asset loading, Django hashed file support, actual Uprava room/agent membership, graceful fallback.
- `tools/office_v14b/src/campus.mjs`: B6 > B5 > B4 > procedural compositing order, existing hit targets, scene state and selected-agent Inspector unchanged.
- `tools/office_v14b/src/camera.mjs`: focused view fits **room bounds** rather than whole campus plate; unfocused camera unchanged.
- Django `office.html` meta declarations via `{% static %}`; no changes to models, API routes, business logic, CSP or static config.
- **12 new Node tests**: seven assets/privacy/fallback and five focused-camera checks (7 B6 + 4 camera); previously available B5 tests add 10, so **22 relevant tests passed locally**.
- Original art is deterministic; regenerate via `python tools/office_v14b/generate_b6_art.py` if `Pillow` and `CairoSVG` are available. The generator is **not called in production**.

## Visual-design limitations

This is a substantially smoother and higher-resolution **2.5D vector illustration**, not a Blender render or cinematic Pixar-quality scene. The character designs are **generic illustrations**, not likenesses derived from protected portrait photographs. Artwork is not evidence of RUNNING tasks; only confirmed API activity can establish it.

## Production workflow for Claude

```bash
# From the repository root, with no uncommitted work.
git checkout main
git pull --ff-only
git switch -c feature/virtual-office-v14b6
# Copy the patch from the handoff ZIP to the repo root.
git apply --check PR_B6_Executive_Art_Pilot.patch
git apply --binary PR_B6_Executive_Art_Pilot.patch

git diff --check
cd tools/office_v14b
npm ci
npm run check
npm run build
cd ../..
python tools/canon_lint.py
ruff check .
python manage.py makemigrations --check --dry-run
python -m pytest
```

The four required gates run against the existing configured PostgreSQL/pgvector environment, as in CI. Running the separate Node check and `npm run build` is also mandatory.

## UI verification

1. Open `/console/office` with an authorized session. On overview the **real** Uprava must show the new smooth artwork, while all other rooms stay unchanged.
2. Click the Uprava title to focus: camera zoom is noticeably larger; 2K detail background is shown with preserved agent positions and hitboxes.
3. Click Ivana/Tamás: the correct **existing** Django inspector and deep link open. Both sprites remain illustrational.
4. Filter by department/search/status, resize browser, use zoom keys/mouse wheel, toggle accessible DOM fallback. No blank canvas, no false RUNNING indicator.
5. Disable B6 files / return 404 in DevTools: **B5**, then B4/procedural art still loads without an exception. Verify separately when one avatar PNG is unavailable.
6. Check DevTools requests contain ONLY same-origin URLs and work after `collectstatic` under ManifestStaticFilesStorage, with CSP unchanged. Verify no portrait or private JSON in public PNGs.
7. Capture **real** whole-building and detail-view screenshots after build. `PR_B6_Uprava_Preview.jpg` is only a synthetic art preview and is **not** a production screenshot.
8. If the owner rejects the visual style, do not merge B6; retain B5. Premium 3D will require a proper modeled/rendered art pipeline, not additional procedural geometry.

## Change ownership

Only frontend/static art and a pure camera calculation change. Django agent orchestration, permissions, bridge, profiles and database are **untouched**. Owner approval required for merge. Original B5 baseline verified by exact Git blob hashes for touched files.
