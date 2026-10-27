# Connection rules for :memory: databases

A :memory: database exists only for the lifetime of the connection that
created it. Each `sqlite3.connect(":memory:")` call opens a NEW, independent
database; data created on one connection is invisible to any other connection,
and closing the connection destroys all of its data. Keep a single connection
open for the whole setup-and-query workflow.

Setting up a table and running queries:

1. Open one connection with `sqlite3.connect(":memory:")` and keep it for the
   whole task.
2. Create the schema and insert the data on that connection.
3. Run all subsequent SELECT statements on the same connection; do not open a
   second `:memory:` connection to query the data.
4. Close the connection only when the task is fully finished, since closing
   discards the in-memory database.
