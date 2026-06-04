# Importers

> **Note:** The Phase 1 import engine is built and lives in
> [`../importer.py`](../importer.py), driven by the web UI under **Import**.
> This directory is kept as a placeholder for future per-platform helper
> scripts (Phase 2 API pulls). The CSV pipeline does **not** live here.

How the live import works (see [`../docs/IMPORT_WORKFLOW.md`](../docs/IMPORT_WORKFLOW.md)):

1. Read a CSV export.
2. Apply the matching column-mapping template from `../docs/column-mappings/`.
3. Normalize (dates → ISO, money → integer cents, emails/phones cleaned).
4. Run the matching ladder against existing donors (email → name+address → name+phone).
5. Stage into an `import_batch` for review.
6. Commit on approval (recompute donor totals) or roll back later.

The engine uses the Python standard library plus `pyyaml` for the mapping
templates — no pandas/openpyxl, to keep the VPS install lean. XLSX and direct
API imports are Phase 2.
