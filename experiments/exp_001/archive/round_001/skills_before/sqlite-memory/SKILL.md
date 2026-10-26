# sqlite-memory

Guidance for building and testing with SQLite in-memory databases.

Use `sqlite3.connect(":memory:")` for ephemeral test databases and for
demos that do not need persistence. It is fast, isolated, and requires no
cleanup.

## Rules

- Prefer an in-memory database for unit tests and demonstrations.
- Follow the connection rules in `reference/connections.md`.
- Verify the final state by querying the tables you created.
