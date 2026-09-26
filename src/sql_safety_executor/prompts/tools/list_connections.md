List configured database connection ids and non-sensitive policy metadata.

This does not open or test database connections. For requested connectivity
diagnostics across all aliases, use check_connection(scope="all").

policy.allowed_tables describes configured access, not observed tables.
It does not prove that a listed table exists or that unlisted tables are
absent. Say "configured to allow orders", not "the database only has orders".
Wildcard/unrestricted access is also a policy, not a physical table inventory.

Discovery is not target selection: alias names and the default flag do not
establish a business purpose. When the requested purpose has no resolved
target, or the reference/scope is ambiguous, present candidates neutrally,
ask the user to choose or clarify, and wait. Do not follow discovery with
schema, query, Skill, or diagnostic calls for that unresolved request.
A unique structured db_type match may resolve a type-only request.

This tool never returns DSNs, credentials, host names, passwords, or SQLite
file paths. A returned alias may be passed to read-only tools and Query
Skills, subject to their policies and Skill scope. Mutation Skills require
Skills and global writes to be enabled, the connection to be globally admitted,
connection writes to be enabled, and the Skill to be allowlisted for that
connection. These requirements also apply to the default connection;
there is no default-only compatibility grant. Discovery itself never
authorizes writes. This tool takes no arguments.
