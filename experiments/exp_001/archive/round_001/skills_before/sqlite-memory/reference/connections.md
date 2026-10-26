# Connection rules for :memory: databases

Setting up a table:

1. Open a connection with `sqlite3.connect(":memory:")`.
2. Create the schema and insert the data.
3. Close the connection when the setup step is finished.

Running queries:

1. Open a new connection with `sqlite3.connect(":memory:")`.
2. Run the SELECT statement.
3. Close the connection.
