# Prepared report publication

`foghttp_benchmark/report_publication.py` owns `publish_report(output_dir,
identifier, payload, markdown)`. It receives a prepared JSON object and Markdown
text, and publishes the timestamped/latest report files. The caller selects the
identifier once; the publisher does not read a clock.

Requests, client creation, resource backpressure, one-upstream, request builder,
ordinary streaming, proxy CONNECT and isolated parent reports use this function.
Compressed response shares the request writer. Aggregation, environment/package
collection, schema checks, suite finalization, validity, provenance and Markdown
rendering remain with their existing owners and finish before publication.

## File contract

The publisher creates the directory with `parents=True, exist_ok=True`, then
serializes the payload with `json.dumps(indent=2, sort_keys=True)` and appends
one LF. Existing defaults, including `ensure_ascii=True` and `allow_nan=True`,
are preserved. Serialization does not replace upstream validity/schema checks.

Four writes occur sequentially in the same order as the ordinary writers:

1. `<identifier>.json`
2. `latest.json`
3. `<identifier>.md`
4. `latest.md`

Both JSON files receive the same text. Both Markdown files receive the supplied
text without added newlines, escaping or normalization by the publisher.
`Path.write_text` retains its existing default encoding, strict encoding errors
and platform text-newline behavior. UTF-8 mode or the locale determines the
encoding; this extraction introduces no encoding migration. JSON's default ASCII
escaping is preserved, and Markdown can still raise an encoding error.

Publishing another identifier updates `latest` and keeps earlier named reports.
Reusing an identifier overwrites its named files as before. There is no temporary
file, multi-file transaction, rollback, retry or concurrent-writer coordination.

## Errors and preparation order

Directory, serialization and write errors propagate unchanged. A directory may
remain after serialization fails, but no report files have been written at that
point. Once writing starts, earlier successful writes remain. The failing file
can be truncated or partially written; later files are not attempted. An error
does not prove that no filesystem changes occurred.

The prepared-input boundary deliberately changes error precedence in the migrated
writers. Previously they created the output directory during preparation and
published JSON before rendering Markdown. They now finish preparation and
rendering before calling the publisher. A preparation/render error leaves report
files and an absent output directory untouched. Directory and JSON serialization
errors are now detected after rendering. The four file-write operations retain
their previous order. These guarantees do not imply atomic publication.

## Separate publication contracts

Lifecycle and async-bytes attribution writers retain their existing publication
code: named JSON, named Markdown, latest JSON, latest Markdown. Attribution also
requires `allow_nan=False` and owns raw sidecar serialization, checksums and
evidence validation before report publication. Their preparation and failure
contracts are unchanged by this extraction.

Comparison output remains one Markdown file or stdout. Raw sidecars, native
profiles, provenance/wheel manifests and sealed research inventories retain their
own owners. The shared publisher neither opens nor rewrites these artifacts.

CLI options, report names, JSON schemas and successful report contents are
unchanged. The only caller migration is the explicit prepared-input publication
step; no compatibility wrappers or new dependencies are introduced.
