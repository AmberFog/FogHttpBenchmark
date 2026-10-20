# Report rendering

`foghttp_benchmark/rendering.py` owns Markdown template configuration, filters
and rendering. Report writers retain environment collection, package/source
identity, validity classification, evidence verification and filesystem
publication. Measurement code and FogHTTP are unchanged.

## Preparation and rendering

Preparation has two explicit inputs to rendering:

- `load_report_template(name)` reads the packaged template sources into a
  Jinja `DictLoader`. The returned `Template` resolves imports and includes
  from memory, including on its first render.
- A ready context supplies all displayed data. `SuiteRenderContext[Row]`
  retains each suite's own aggregate type and requires timestamp, arguments,
  skipped clients, calculated validity and `RenderEnvironment`. The environment
  contains displayed Python and platform strings; it never probes the host.

`ProxyRenderContext` additionally requires the already redacted proxy URL.
`ProfileRenderContext` carries lifecycle or async-bytes aggregate, metadata and
runs, after the writer's existing provenance/evidence/validity checks.
`IsolationRenderContext` receives prepared child rows, isolation unit, run count
and merged validity. Comparison rendering accepts the existing, fully calculated
`ComparisonResult` directly.

The `render_*_markdown` functions take a loaded template and the corresponding
ready data. They return text without collecting environment data, classifying
validity, reading evidence, loading files, writing reports or changing inputs.
These functions do not create a universal aggregate model or select suite policy.

For example, an ordinary writer supplies its already prepared values:

```python
from foghttp_benchmark.rendering import (
    RenderEnvironment,
    SuiteRenderContext,
    load_report_template,
    render_suite_markdown,
)

template = load_report_template("report.md.j2")
context = SuiteRenderContext(
    timestamp=timestamp,
    args=args,
    aggregate=aggregate,
    skipped=skipped,
    validity=metadata["validity"],
    environment=RenderEnvironment(
        python_version=display_python_version,
        platform_name=display_platform,
    ),
)
markdown = render_suite_markdown(template, context)
```

## Compatibility

Templates, columns, row order, whitespace, optional resource values and escaping
retain their existing behavior. `markdown_table_cell` normalizes CRLF and CR to
LF, escapes pipes with a backslash and replaces LF with `<br>`; Unicode is
preserved. `resource_value` still displays `None` as `unavailable` and retains
the existing numeric formatting.

Internal callers now import renderers, `report_environment` and filters directly
from `foghttp_benchmark.rendering`. The old suite render functions and
`compare.reports.render_compare_markdown` have been removed rather than retained
as import proxies. Comparison callers pass a loaded comparison template as the
first argument to `render_compare_markdown`.

CLI options, JSON fields and schemas, validity gates, provenance requirements
and publication order are unchanged. Existing saved evidence is not rewritten.
The ordinary/isolation writers now finish rendering before calling the shared
[prepared report publisher](report-publication.md). That boundary documents the
preparation-error migration and sequential file failure behavior separately.
