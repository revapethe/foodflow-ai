"""Optional PostgreSQL adapter for the existing read-only analytics SQL contract."""


class WarehouseUnavailable(RuntimeError):
    pass


class PostgresConnection:
    """Request-scoped connection; parameters are bound by the PostgreSQL driver."""
    def __init__(self, dsn):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise WarehouseUnavailable('Install requirements-postgres.txt') from None
        self.error = psycopg.Error
        self.db = None
        try:
            self.db = psycopg.connect(dsn, autocommit=True, row_factory=dict_row, connect_timeout=5)
            self.db.execute("SET default_transaction_read_only=on")
            self.db.execute("SET statement_timeout='5s'")
            self.db.execute('SET search_path=foodflow_analytics,pg_catalog')
        except psycopg.Error:
            self.close()
            raise WarehouseUnavailable('PostgreSQL unavailable') from None

    def execute(self, query, params=()):
        # Only static application SQL uses this adapter; user values remain bound.
        if query == 'BEGIN':
            query = 'BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'
        try:
            return self.db.execute(query.replace('?', '%s'), params)
        except self.error:
            raise WarehouseUnavailable('PostgreSQL query failed') from None

    def close(self):
        if self.db is not None:
            self.db.close()
