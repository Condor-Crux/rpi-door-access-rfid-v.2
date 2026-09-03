import datetime
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.infrastructure.models import Base

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}
)

# WAL mode prevents SSE long-poll from blocking the RFID write loop
@event.listens_for(engine, "connect")
def set_wal_mode(dbapi_connection, connection_record):
    dbapi_connection.execute("PRAGMA journal_mode=WAL")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_ticket_ledger_composite_unique(conn):
    """Widens the ledger's uniqueness rule from "número alone" to "(número,
    tipo)" — the same ticket número CAN repeat under a different tipo (e.g.
    A-10000111 and B-10000111 are different vouchers), only the exact pair
    must stay unique forever.

    The old rule was a column-level UNIQUE baked into invoice_number itself,
    which SQLite can't ALTER away — so when that old constraint is detected,
    the table is rebuilt: copy every row into a same-shaped table with the
    new composite index, drop the old table, rename. Existing data already
    satisfies the new (weaker) rule, since it was already fully unique on
    invoice_number alone. Skipped once already migrated — a fresh install
    (via create_all) never has the old constraint to begin with.
    """
    exists = conn.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ticket_carga_redemptions'"
    )).fetchone()
    if not exists:
        return

    old_single_column_unique = False
    for idx in conn.execute(text("PRAGMA index_list('ticket_carga_redemptions')")).fetchall():
        idx_name, is_unique = idx[1], idx[2]
        if not is_unique:
            continue
        cols = [row[2] for row in conn.execute(text(f"PRAGMA index_info('{idx_name}')")).fetchall()]
        if cols == ["invoice_number"]:
            old_single_column_unique = True
            break
    if not old_single_column_unique:
        return

    conn.execute(text(
        "CREATE TABLE ticket_carga_redemptions_v2 ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "invoice_number INTEGER NOT NULL, "
        "account_id VARCHAR NOT NULL, "
        "credits INTEGER NOT NULL, "
        "ticket_type VARCHAR, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    ))
    conn.execute(text(
        "INSERT INTO ticket_carga_redemptions_v2 "
        "(id, invoice_number, account_id, credits, ticket_type, created_at) "
        "SELECT id, invoice_number, account_id, credits, ticket_type, created_at "
        "FROM ticket_carga_redemptions"
    ))
    conn.execute(text("DROP TABLE ticket_carga_redemptions"))
    conn.execute(text("ALTER TABLE ticket_carga_redemptions_v2 RENAME TO ticket_carga_redemptions"))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_ticket_carga_redemptions_invoice_type_unique "
        "ON ticket_carga_redemptions (invoice_number, ticket_type)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_ticket_carga_redemptions_account_id "
        "ON ticket_carga_redemptions (account_id)"
    ))
    conn.commit()


def _column_affinity_is_integer(conn, table, column) -> bool:
    for row in conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall():
        # row: cid, name, type, notnull, dflt_value, pk
        if row[1] == column:
            return (row[2] or "").upper() == "INTEGER"
    return False


def _migrate_invoice_number_to_text(conn):
    """invoice_number is an 8-digit code where a leading zero is
    significant (e.g. "00012345" is a different ticket than "12345"), not a
    numeric quantity. A column with INTEGER affinity — which is what both
    accounts.invoice_number and ticket_carga_redemptions.invoice_number had
    — makes SQLite coerce any inserted value to an integer, silently
    dropping leading zeros. Both need TEXT affinity instead.

    SQLite can't ALTER a column's declared type, so each table is rebuilt
    (copy into a same-shaped table with the new column type, drop, rename)
    when the old INTEGER affinity is still detected — skipped once already
    migrated. Existing values are preserved as they were already stored:
    none of them had a leading zero to begin with, since they all predate
    this rule.
    """
    if _column_affinity_is_integer(conn, "accounts", "invoice_number"):
        conn.execute(text(
            "CREATE TABLE accounts_v2 ("
            "account_id VARCHAR NOT NULL PRIMARY KEY, "
            "status VARCHAR, "
            "expiration_date DATETIME, "
            "credits INTEGER, "
            "user_id INTEGER, "
            "key_type VARCHAR, "
            "invoice_number VARCHAR, "
            "ticket_type VARCHAR, "
            "FOREIGN KEY(user_id) REFERENCES users (id))"
        ))
        conn.execute(text(
            "INSERT INTO accounts_v2 "
            "(account_id, status, expiration_date, credits, user_id, key_type, invoice_number, ticket_type) "
            "SELECT account_id, status, expiration_date, credits, user_id, key_type, "
            "CAST(invoice_number AS TEXT), ticket_type FROM accounts"
        ))
        conn.execute(text("DROP TABLE accounts"))
        conn.execute(text("ALTER TABLE accounts_v2 RENAME TO accounts"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_accounts_invoice_number_ticket_unique "
            "ON accounts (invoice_number, ticket_type) "
            "WHERE key_type = 'ticket_carga' AND invoice_number IS NOT NULL"
        ))
        conn.commit()

    if _column_affinity_is_integer(conn, "ticket_carga_redemptions", "invoice_number"):
        conn.execute(text(
            "CREATE TABLE ticket_carga_redemptions_v3 ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "invoice_number VARCHAR NOT NULL, "
            "account_id VARCHAR NOT NULL, "
            "credits INTEGER NOT NULL, "
            "ticket_type VARCHAR, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "INSERT INTO ticket_carga_redemptions_v3 "
            "(id, invoice_number, account_id, credits, ticket_type, created_at) "
            "SELECT id, CAST(invoice_number AS TEXT), account_id, credits, ticket_type, created_at "
            "FROM ticket_carga_redemptions"
        ))
        conn.execute(text("DROP TABLE ticket_carga_redemptions"))
        conn.execute(text("ALTER TABLE ticket_carga_redemptions_v3 RENAME TO ticket_carga_redemptions"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_ticket_carga_redemptions_invoice_type_unique "
            "ON ticket_carga_redemptions (invoice_number, ticket_type)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ticket_carga_redemptions_account_id "
            "ON ticket_carga_redemptions (account_id)"
        ))
        conn.commit()


def _run_migrations():
    """Idempotent ALTER TABLE migrations — safe to run on every startup."""
    migrations = [
        "ALTER TABLE users ADD COLUMN deleted_at DATETIME",
        "ALTER TABLE users ADD COLUMN document_type VARCHAR",
        "ALTER TABLE users ADD COLUMN document_number VARCHAR",
        "ALTER TABLE users ADD COLUMN nationality VARCHAR DEFAULT 'AR'",
        "ALTER TABLE companies ADD COLUMN deleted_at DATETIME",
        "ALTER TABLE accounts ADD COLUMN key_type VARCHAR DEFAULT 'particulares'",
        "ALTER TABLE accounts ADD COLUMN invoice_number VARCHAR",
        "CREATE INDEX IF NOT EXISTS ix_access_logs_timestamp ON access_logs (timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_access_logs_account_id ON access_logs (account_id)",
        "CREATE INDEX IF NOT EXISTS ix_access_logs_event_type ON access_logs (event_type)",
        # Cross-process SSE bus: publishers append rows, SSE streams poll by id.
        "CREATE TABLE IF NOT EXISTS sse_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_type VARCHAR NOT NULL, "
        "data TEXT NOT NULL, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        # A ticket de carga is a physical paper voucher — the (número, tipo)
        # pair must never be redeemed twice, but the same número IS allowed
        # to repeat under a different tipo. Dropped and recreated every
        # startup so an older single-column definition is always replaced by
        # this one — CREATE ... IF NOT EXISTS alone would never update an
        # index that already exists under this name with a stale definition.
        # Partial: only constrains rows where key_type='ticket_carga' and
        # invoice_number is set. Safety net behind the application-level
        # check in app/api/endpoints.py.
        "DROP INDEX IF EXISTS ix_accounts_invoice_number_ticket_unique",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_accounts_invoice_number_ticket_unique "
        "ON accounts (invoice_number, ticket_type) WHERE key_type = 'ticket_carga' AND invoice_number IS NOT NULL",
        # Permanent ledger of every ticket de carga ever redeemed — lets one
        # llave accumulate credits from several tickets over time. See
        # LoadedTicketModel in app/infrastructure/models.py.
        "CREATE TABLE IF NOT EXISTS ticket_carga_redemptions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "invoice_number VARCHAR NOT NULL, "
        "account_id VARCHAR NOT NULL, "
        "credits INTEGER NOT NULL, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE INDEX IF NOT EXISTS ix_ticket_carga_redemptions_account_id "
        "ON ticket_carga_redemptions (account_id)",
        # One-time backfill: any ticket_carga card that already had an
        # invoice_number before this ledger existed becomes that ticket's
        # first (and, for now, only) redemption row. Best-effort — the
        # card's current credit balance is attributed to that original
        # ticket, since we have no earlier record splitting it out. Guarded
        # by NOT EXISTS so it only ever inserts each invoice_number once,
        # safe to run on every startup. created_at is set explicitly here
        # (not left to a table default) because Base.metadata.create_all()
        # runs before this and creates the table straight from the
        # LoadedTicketModel mapping — which, being a NOT NULL column with
        # only a Python-side default, leaves no DB-level default for a raw
        # SQL insert like this one to fall back on.
        "INSERT INTO ticket_carga_redemptions (invoice_number, account_id, credits, created_at) "
        "SELECT a.invoice_number, a.account_id, a.credits, CURRENT_TIMESTAMP FROM accounts a "
        "WHERE a.key_type = 'ticket_carga' AND a.invoice_number IS NOT NULL "
        "AND NOT EXISTS ("
        "SELECT 1 FROM ticket_carga_redemptions t WHERE t.invoice_number = a.invoice_number"
        ")",
        # Ticket type ("A"/"B"/"Y"/"R") on both the card's denormalized last
        # ticket and each permanent ledger row. Nullable — tickets redeemed
        # before this field existed (including the ones the migration above
        # backfills) simply have no type on record.
        "ALTER TABLE accounts ADD COLUMN ticket_type VARCHAR",
        "ALTER TABLE ticket_carga_redemptions ADD COLUMN ticket_type VARCHAR",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # Column/index already exists — safe to ignore
        try:
            _migrate_ticket_ledger_composite_unique(conn)
        except Exception:
            pass  # Already migrated, or nothing to migrate yet — safe to ignore
        try:
            _migrate_invoice_number_to_text(conn)
        except Exception:
            pass  # Already migrated, or nothing to migrate yet — safe to ignore


def _seed():
    from app.infrastructure.models import CompanyModel
    with SessionLocal() as db:
        if not db.query(CompanyModel).filter_by(name="Particulares").first():
            db.add(CompanyModel(name="Particulares"))
            db.commit()


def init_db():
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    _seed()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
