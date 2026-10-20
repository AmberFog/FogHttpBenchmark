# Suite composition

`application/composition.py` contains the explicit mapping of ordinary benchmark
suites. Each `SuiteDefinition` connects four responsibilities:

- `run(args, *, progress=None)` executes suite-local orchestration in a child.
- `select_clients(args)` projects supported client names and skip reasons for
  parent process isolation.
- `isolation_scenarios(args)` projects effective scenario arguments for parent
  process planning.
- `finalize_report(rows, children_metadata)` finalizes suite-owned aggregate
  values and metadata after child reports have been combined.

`get_suite(name)` is the only supported-suite lookup for this execution path.
It raises `ValueError` for an unknown name before discovery or workload startup.
The parent and child resolve the same mapping; there is no fallback to requests.

| Suite | Orchestration owner | Parent client selection | Isolation scenarios |
| --- | --- | --- | --- |
| requests | `request_suite.py` | Common client registry | Effective scenarios |
| client-creation | `creation/suite.py` | Common client registry | None |
| resource-backpressure | `resource/suite.py` | Common registry, then FogHTTP stats capability | Effective scenarios |
| compressed-response | `compressed_response/suite.py` | Common client registry | Effective scenarios |
| one-upstream | `one_upstream/suite.py` | One-upstream client registry | Effective scenarios |
| request-builder | `request_builder/suite.py` | Request-builder client registry | Effective scenarios |
| response-streaming | `streaming/suite.py` | Streaming client registry | Effective scenarios |
| proxy-connect | `proxy_connect/suite.py` | Proxy CONNECT client registry | Effective scenarios |

The mapping contains function references, not a plugin discovery mechanism or
a common execution algorithm. Suite-local functions own parameter validation,
plans, server contexts, workload invocation, settling and report publication.
Sync/async workers and timing boundaries keep their existing owners.

The application supplies client-selection, scenario-projection and report-finalization callbacks
to the process launcher. The launcher invokes them using effective arguments,
builds sequential child commands and preserves cooldown, diagnostics, failure
handling and report merge. It does not contain a table of suite identities.
Suite-specific post-merge report policies live beside their suite. The launcher
passes the required finalizer to the generic report merger. See
[merged report semantics](merged-report-semantics.md) for its guarded contract.

Selection preserves requested client order and duplicate requested names. Skip
reasons retain their existing keys and precedence. In the child, common client
discovery rejects an empty selection before suite parameter validation;
resource-backpressure then applies its additional FogHTTP requirement.
Specialized suites retain their own discovery and error messages.

`suite_selection.py` owns shared CSV parsing, common-client availability checks
and the projection from typed client specs to isolation names. Each specialized
suite uses its own registry for both parent selection and child orchestration.
Client specs retain the mode-specific factories introduced by TASK-047.

No execution layer reapplies CLI defaults. Client-creation does not split by
scenario even if scenarios were explicitly supplied. Other suites preserve
the scenario list exactly after CSV parsing, including order and duplicates.
An empty projection retains the existing per-client process plan.

Lifecycle and async-bytes profiles continue through the parent-owned streaming
launcher. The ordinary suite mapping does not execute those profiles or bypass
their provenance, integrity or lifecycle checks.

## Adding a suite

1. Implement its orchestration beside its scenarios, typed client registry and
   runner. Keep server ownership, validation and reporting explicit there.
2. Add one `SuiteDefinition` to `SUITES`, using the appropriate selection,
   scenario-projection and report-finalization functions. For example, connect
   `SuiteDefinition(local.run_suite, local.select_clients, scenario_names, preserve_merged_report)`
   when no suite-specific finalization is needed. This finalizer is required;
   it cannot replace the mandatory general validity checks.
3. Add parent-selection, child-dispatch, fixed-seed plan and cleanup/error tests.
   Verify unsupported clients, unknown cases and effective argument forwarding.
4. Deliberately extend the public CLI defaults, report schemas and merge policy
   where required. Those contracts are not generated from this runtime mapping.

## Internal import migration

`application.suites` and the duplicate `isolation.selection` and
`isolation.scenarios` modules have been removed. Use `composition.get_suite`
for ordinary suite resolution. The programmatic parent entry remains
`application.execution.run_benchmark`; internal dispatch is not an isolation
bypass API. No CLI flags, JSON versions or result paths change.
