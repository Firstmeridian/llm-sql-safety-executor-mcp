Check fresh connectivity to one or all configured database connections.

With scope='single' (default), omission of connection_id selects only the default.
For a generic connectivity request with no target clues and no resolved
conversational/application target, check only the default. For a resolved
target, pass connection_id explicitly. An unresolved purpose/role, ambiguous
reference, or irreconcilable scope restrictions require clarification and waiting first;
only list_connections() may be used to offer candidates. Do not probe the default
while waiting. A successful check does not establish the user's intended target.
A prohibition on accessing a target includes this connection check.
If a broader connectivity request explicitly permits only one resolved alias
or the default, check only that target and state that others were not checked.
If partial checks are explicitly rejected, ask and wait instead.
Use scope='all' only when the user clearly requests and permits ALL configured
connections, including an unambiguous continuation of a confirmed all-connection
request. A generic connection problem or missing alias alone does not request all.
scope='all' forbids a non-null connection_id. A prohibition on any configured
target rules out scope='all'. Do not call it as a routine prerequisite before queries;
use it when requested or after an operation reports a connection failure.

Both scopes use disposable connections, leaving business connections and transactions
alone. SQLite files open read-only; :memory: checks only a fresh memory connection.
SQLite WAL auxiliary files may still involve filesystem writes.
This does not verify business pool health, tables, Skill readiness or write privileges.
Within a 30-second budget (shortened for a smaller MCP timeout), return
connected/failed results and timeout/not_checked entries with connected=null.
Incomplete checks are not proof of connection failure. Report counts and
all_connected cover only the selected scope; single returns one results entry.
Underlying checks may continue cleaning up after the response; any new diagnostic
then reports busy. Busy, stopped, or disabled diagnostics return an MCP tool error,
not a report status. cleanup_failed records an observed cleanup exception separately
from connectivity; it disables all diagnostics until the server process restarts.
A false flag means no failure observed at report time, not verified release.