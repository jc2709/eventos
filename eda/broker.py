"""Broker pub/sub persistente y didáctico. Un paso entrega un evento a un consumidor."""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone


class Broker:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.handlers = {}
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS events(
          seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, type TEXT NOT NULL,
          producer TEXT NOT NULL, correlation_id TEXT NOT NULL,
          occurred_at TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS deliveries(
          id INTEGER PRIMARY KEY, event_id TEXT REFERENCES events(id),
          consumer TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
          UNIQUE(event_id,consumer));
        CREATE TABLE IF NOT EXISTS traces(
          id INTEGER PRIMARY KEY, event_id TEXT, consumer TEXT, result TEXT, detail TEXT);
        ''')

    def subscribe(self, consumer, types, handler):
        self.handlers[consumer] = (set(types), handler)

    def publish(self, event_type, producer, correlation_id, payload):
        # El llamador controla la transacción que incluye el hecho y sus entregas.
        event = dict(id=str(uuid.uuid4()), type=event_type, producer=producer,
                     correlation_id=correlation_id,
                     occurred_at=datetime.now(timezone.utc).isoformat(),
                     version=1, payload=payload)
        self.db.execute('INSERT INTO events(id,type,producer,correlation_id,occurred_at,version,payload) VALUES(?,?,?,?,?,?,?)',
                        (event['id'], event_type, producer, correlation_id,
                         event['occurred_at'], 1, json.dumps(payload, ensure_ascii=False)))
        for consumer, (types, _) in self.handlers.items():
            if event_type in types:
                self.db.execute('INSERT INTO deliveries(event_id,consumer) VALUES(?,?)',
                                (event['id'], consumer))
        return event

    def step(self):
        with self.lock, self.db:
            row = self.db.execute('''SELECT d.*, e.type, e.producer, e.correlation_id,
                  e.occurred_at, e.version, e.payload FROM deliveries d
                  JOIN events e ON e.id=d.event_id WHERE d.status IN ('pending','retry')
                  ORDER BY d.attempts,d.id LIMIT 1''').fetchone()
            if row is None:
                return None
            event = dict(row)
            event['payload'] = json.loads(row['payload'])
            event['id'] = row['event_id']
            attempt = row['attempts'] + 1
            self.db.execute('SAVEPOINT delivery')
            try:
                detail = self.handlers[row['consumer']][1](event)
                self.db.execute('UPDATE deliveries SET status="done", attempts=?, error=NULL WHERE id=?',
                                (attempt, row['id']))
                self.db.execute('INSERT INTO traces(event_id,consumer,result,detail) VALUES(?,?,?,?)',
                                (event['id'], row['consumer'], 'done', detail))
                self.db.execute('RELEASE delivery')
            except Exception as exc:
                self.db.execute('ROLLBACK TO delivery')
                self.db.execute('RELEASE delivery')
                status = 'failed' if attempt >= 3 else 'retry'
                self.db.execute('UPDATE deliveries SET status=?, attempts=?,error=? WHERE id=?',
                                (status, attempt, str(exc), row['id']))
                self.db.execute('INSERT INTO traces(event_id,consumer,result,detail) VALUES(?,?,?,?)',
                                (event['id'], row['consumer'], status, str(exc)))
            return dict(self.db.execute('SELECT * FROM deliveries WHERE id=?', (row['id'],)).fetchone())

    def retry_failed(self):
        with self.lock, self.db:
            return self.db.execute('UPDATE deliveries SET status="pending",attempts=0,error=NULL WHERE status="failed"').rowcount

    def close(self):
        self.db.close()
