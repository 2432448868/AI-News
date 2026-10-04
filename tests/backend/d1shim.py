"""sqlite3-backed D1 double for tests.

Exposes the same surface the real binding gives backend/db.py:
prepare(sql).bind(*params) → .all()/.first()/.run(), plus db.batch([...])
as one transaction.
"""
import sqlite3


class Statement:
    __slots__ = ('conn', 'sql', 'params')

    def __init__(self, conn, sql):
        self.conn = conn
        self.sql = sql
        self.params = ()

    def bind(self, *params):
        self.params = tuple(params)
        return self

    async def all(self):
        cursor = self.conn.execute(self.sql, self.params)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        return {'results': [dict(zip(columns, row)) for row in cursor.fetchall()]}

    async def first(self):
        rows = (await self.all())['results']
        return rows[0] if rows else None

    async def run(self):
        self.conn.execute(self.sql, self.params)


class D1:
    def __init__(self, schema_sql):
        # isolation_level=None → autocommit, closest to D1's behavior.
        self.conn = sqlite3.connect(':memory:', isolation_level=None)
        self.conn.execute('PRAGMA foreign_keys = ON')
        self.conn.executescript(schema_sql)

    def prepare(self, sql):
        return Statement(self.conn, sql)

    async def batch(self, statements):
        self.conn.execute('BEGIN')
        try:
            for stmt in statements:
                self.conn.execute(stmt.sql, stmt.params)
            self.conn.execute('COMMIT')
        except Exception:
            self.conn.execute('ROLLBACK')
            raise

    def close(self):
        self.conn.close()
