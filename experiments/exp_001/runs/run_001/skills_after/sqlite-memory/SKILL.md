# sqlite-memory

Guidance for building and testing with SQLite in-memory databases.

Use `sqlite3.connect(":memory:")` for ephemeral test databases and for
demos that do not need persistence. It is fast, isolated, and requires no
cleanup. An in-memory database is isolated per connection: each new connection
starts empty, so create, populate, and query it on one shared connection
rather than opening a fresh connection per step.

## Rules

- Prefer an in-memory database for unit tests and demonstrations.
- Reuse a single connection for the whole task, because each new `:memory:`
  connection creates a separate database and closing destroys the data. See
  `reference/connections.md` for the detailed connection rules.
- Reuse a single connection for schema creation, inserts, and queries; never
  assume data created on one `:memory:` connection is visible on another.
- Verify the final state by querying the tables you created.
