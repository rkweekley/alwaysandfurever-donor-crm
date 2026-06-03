# Column Mapping Templates

Each platform exports donations with its own column names. These templates map each
platform's columns → our standard fields (the `donations`/`donors` columns).

- `_standard_fields.md` — the canonical target fields every mapping points to.
- One `*.yaml` per platform. `source_column` is what the platform calls it;
  `standard_field` is ours. `null` source means "platform doesn't provide this —
  fill manually or leave blank."

These are **starting points**. Real exports vary by account settings and date, so
the importer always lets you confirm/adjust the mapping before committing (and saves
the final mapping on the import batch for audit).

> The sample column names below reflect common/typical exports. Verify against an
> actual export from each account before the first real import — Zeffy and Facebook
> in particular change their CSV headers periodically.
