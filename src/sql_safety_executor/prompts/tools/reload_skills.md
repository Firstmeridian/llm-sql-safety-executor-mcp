Publish deployed Skill changes from the configured directory. Choose skill_type explicitly for Mutation updates; the default query reload preserves Mutation code and previews. Ordinary discovery/execution use the loaded snapshot without reloading files.

Validate a candidate, then atomically add, update, disable or remove the selected kind. Failure keeps the previous catalog and previews. Mutation reload imports trusted Python entry code; unchanged entries are reused. It is not a sandbox or shared-dependency reload, and publication cannot undo module top-level side effects.

Changed/removed Mutations invalidate their pending previews, even if the declared version is unchanged. Let the user decide whether to preview again; never automatically execute or retry. Executions admitted before publication may finish on their original version. Other Skills' previews remain valid until their normal expiry/consumption.

Before reporting success, check revision, added/changed/removed and invalidated_previews, then verify affected details/parameters in the actual consuming instance. Reuse task-relevant authorized execution when needed to check changed behavior; do not write merely to test refresh. Publication alone proves neither readiness, authorization nor business correctness. After a lost response, inspect the loaded state instead of automatically reloading again.

No connection, grant, configuration, core-code or shared Python dependency reload; those changes require restart. Publication is per receiving server instance, not broadcast. Continue normal authorization and execution checks.
