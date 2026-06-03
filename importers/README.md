# Importers

Phase 1 import scripts live here. The plan (see `../docs/IMPORT_WORKFLOW.md`):

1. Read a CSV/XLSX export.
2. Apply the matching column-mapping template from `../docs/column-mappings/`.
3. Normalize (dates → ISO, money → integer cents, emails/phones cleaned).
4. Run the matching ladder against existing donors.
5. Stage into an `import_batch` for review.
6. Commit on approval; recompute donor giving totals.

Suggested first implementation: a small Python tool using `pandas` + `openpyxl`
for parsing and `pyyaml` for the mapping templates, writing to the SQLite database
defined in `../db/schema.sql`. Nothing is built yet — this is the Phase 1 target.
