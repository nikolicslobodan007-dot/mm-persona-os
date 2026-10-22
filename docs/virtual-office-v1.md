# Virtual Office V1.2 — prvi izolovani korak

Status: **DRAFT PR — nije za merge** dok Claude ne pregleda backend i dok četiri kapije ne prođu na ažurnoj osnovi grane.

- Ugovor: `contracts/openapi/office-v1.yaml` (LOCKED/APPROVED V1.2).
- Novi, read-only moduli: `console/office_bridge.py` i lokalni šablon/JS/CSS u `console`.
- Rute: `/console/office`, `/console/office/api/v1/summary`, `agents`, `agents/<public_id>`, `events`, `/console/office/portraits/<public_id>`.
- Ne menja modele, migracije, raspored workera, orkestraciju, kanonski `/api/v1` ni postojeću medijsku rutu.
- Nema JavaScript/CSS CDN-a, inline JS-a ni inline CSS-a. `console.auth` i TOTP ostaju izvor istine; JSON endpointi vraćaju JSON 401/403, dok HTML ruta koristi `console_view`.
- Razdvojeni `status` i `runtime_environment` nikada se ne tretiraju kao signal stvarnog rada.
- `goal_excerpt` je obavezno `null`; `input_json`, `output_json`, `summary_json`, `AuditEvent.payload`, PII, interni ID-evi i tajne nisu deo izlaza.
- Cursor je random token sa state-om u postojećem Redis kešu, vezan za sesiju, filter, resurs i veličinu stranice; TTL 30 minuta. Events zadržava početnu gornju granicu; bez offseta.
- Portret ima zasebnu rutu i strogo proverava `VisualProfile.reference_asset`, `FACE_REFERENCE`, vlasništvo i MIME; sadržaj se učitava kroz interni S3/MinIO adapter.
- Vizuelni ekran je **funkcionalna osnova**: prikazuje sobe prema stvarnim odeljenjima, a portrete u klikabilnim oznakama. Soft-3D/PixiJS animirani spriteovi dolaze sledećim zasebnim PR-om. Ova prva isporuka ih ne predstavlja kao završene.

## Bezbednosni i QA pregled pre merge-a

1. Potvrditi enum vrednosti i format odgovora prema OpenAPI.
2. Potvrditi auth/TOTP, JSON 401/403 i `console_view` za HTML rutu.
3. Proveriti izolaciju tuđih portreta i drugih tipova medijskih datoteka.
4. Proveriti da `goal_excerpt` nikad nije string i da se ne iznose osetljiva polja.
5. Proveriti cursor istu/drugu sesiju, filter/limit, istekao token, Redis prekid.
6. Proveriti stvarni CSP u browseru i lokalni CSS/JS.
7. Pokrenuti četiri kapije na ažurnoj osnovi: pytest, ruff, canon_lint, `makemigrations --check --dry-run`.
8. Claude pregled bridža i tek zatim vlasnik odlučuje da li je PR spreman za spajanje.
