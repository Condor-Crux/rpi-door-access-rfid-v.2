import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Index, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from typing import Optional

from app.core.time import utcnow

class Base(DeclarativeBase):
    pass

class CompanyModel(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True, default=None)

class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(String)
    last_name: Mapped[str] = mapped_column(String)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("companies.id"), nullable=True)
    document_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    document_number: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    nationality: Mapped[str] = mapped_column(String, default="AR")
    deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True, default=None)

    company = relationship("CompanyModel")

class AccountModel(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="active") # "active" or "inactive"
    expiration_date: Mapped[datetime.datetime] = mapped_column(DateTime)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    # "particulares", "cuenta_corriente" or "ticket_carga"
    key_type: Mapped[str] = mapped_column(String, default="particulares")
    # Número del ticket/comprobante de carga (solo aplica si key_type == "ticket_carga").
    # String, not Integer: it's an 8-digit code where a leading zero is
    # significant (e.g. "00012345" != "12345") — an INTEGER-affinity column
    # would silently drop it.
    invoice_number: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    # Tipo de ticket de carga: "A", "B", "Y" o "R" (solo aplica si key_type == "ticket_carga")
    ticket_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)

    user = relationship("UserModel")

    __table_args__ = (
        # A ticket de carga is a one-time paper voucher: the (número, tipo)
        # pair must never be redeemed twice, permanently — but the same
        # número IS allowed to repeat across different tipo values (e.g.
        # A-10000111 and B-10000111 can coexist). Partial index — other key
        # types leave invoice_number NULL and are unaffected. Declared here
        # so fresh databases (tests, new installs) get it via create_all();
        # existing installs get the same index via the raw-SQL migration in
        # app/infrastructure/database.py (_run_migrations), same pattern as
        # the access_logs indexes below.
        Index(
            "ix_accounts_invoice_number_ticket_unique",
            "invoice_number",
            "ticket_type",
            unique=True,
            sqlite_where=text("key_type = 'ticket_carga' AND invoice_number IS NOT NULL"),
        ),
    )

class LoadedTicketModel(Base):
    """Permanent ledger of every ticket de carga ever redeemed.

    A ticket de carga is a physical, one-time paper voucher: once a (número,
    tipo) pair is redeemed onto a card, that exact pair can never be
    redeemed again — on that same card or any other, ever. The same número
    CAN reappear under a different tipo (A-10000111 and B-10000111 are
    different vouchers). This table (not AccountModel) is the single source
    of truth for that rule, which is what makes "several tickets → one
    llave" possible: many rows here can point at the same account_id.
    AccountModel.invoice_number/ticket_type are kept only as a denormalized
    "most recently loaded ticket" convenience for the compact table views —
    they are not used for the uniqueness check.
    """
    __tablename__ = "ticket_carga_redemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # String, not Integer — see the identical note on AccountModel.invoice_number.
    invoice_number: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.account_id"), nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    # "A", "B", "Y" or "R" — nullable only because tickets redeemed before
    # this field existed were backfilled without one; every new redemption
    # requires it (see app/api/endpoints.py).
    ticket_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        Index("ix_ticket_carga_redemptions_account_id", "account_id"),
        # Composite uniqueness: same número, different tipo is allowed.
        Index(
            "ix_ticket_carga_redemptions_invoice_type_unique",
            "invoice_number",
            "ticket_type",
            unique=True,
        ),
    )


class AccessLogModel(Base):
    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    account_id: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String) # "grant" or "deny"
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_access_logs_timestamp", "timestamp"),
        Index("ix_access_logs_account_id", "account_id"),
        Index("ix_access_logs_event_type", "event_type"),
    )


class AuditLogModel(Base):
    """Immutable system-wide audit trail. Never deleted or updated."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    # Semantic event type: rfid.grant, rfid.deny, user.created, user.deleted,
    # company.created, company.deleted, card.created, card.edited,
    # card.recharged, card.unlinked, batch.blanquear, ticket.loaded
    event_type: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)  # "system" or "admin"
    summary: Mapped[str] = mapped_column(String)  # human-readable one-liner
    details: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # JSON text

    __table_args__ = (
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_event_type", "event_type"),
        Index("ix_audit_logs_actor", "actor"),
    )
