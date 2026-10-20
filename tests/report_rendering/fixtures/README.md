# Rendering fixtures

`contexts.json` contains prepared display inputs for every report template.
`expected.json` stores exact Markdown strings, including trailing newlines.

The expected output was captured before TASK-053 from the preserved source
snapshot, using the original `foghttp_benchmark.reports.report_environment`
and all eleven original report templates. The entry checkout was
`874997e920d612eb29e871c3f92e5babbd68e698` plus the accumulated TASK-042 through
TASK-052 work. These are synthetic rendering fixtures, not measurement results.

Inputs are saved with the project's JSON hook formatting and sorted dictionary
keys, then read back before the original templates capture expected output.
This makes dictionary representations match the actual saved inputs. Aggregate,
reason and diagnostic lists retain their deliberate input order.

The cases preserve deliberate input ordering, unavailable and measured zero
resources, optional values, skipped clients, invalidity warnings, package source
versions, comparison versions, resource coverage and Markdown escaping. Unicode,
pipes and mixed CRLF/CR/LF endings exercise the unchanged cell filter.

Do not regenerate expected output from the refactored renderer to make a failed
test pass. A deliberate output change requires review of the full changed text.
