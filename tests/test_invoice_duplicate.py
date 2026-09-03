import datetime

from app.core.time import utcnow
from app.infrastructure.models import UserModel, AccountModel, LoadedTicketModel


def _make_user(db_session, first_name="Pablo", last_name="Crux"):
    user = UserModel(first_name=first_name, last_name=last_name)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_ticket_card(client, account_id, invoice_number, user_id, ticket_type="A", decoy_credits=999):
    """decoy_credits is intentionally implausible (999) — a ticket de carga
    must always net exactly 1 credit no matter what a crafted request sends,
    so tests assert against 1, not against this value."""
    return client.post(
        "/ui/accounts/create",
        data={
            "account_id": account_id,
            "status": "active",
            "expiration_date": (utcnow() + datetime.timedelta(hours=24)).isoformat(),
            "credits": decoy_credits,
            "user_id": user_id,
            "key_type": "ticket_carga",
            "invoice_number": invoice_number,
            "ticket_type": ticket_type,
        },
        headers={"HX-Request": "true"},
    )


def _load_ticket(client, account_id, invoice_number, ticket_type="A"):
    return client.post(
        f"/ui/accounts/{account_id}/load-ticket",
        data={"invoice_number": invoice_number, "ticket_type": ticket_type},
        headers={"HX-Request": "true"},
    )


def test_create_ticket_card_succeeds(client, db_session):
    user = _make_user(db_session)
    response = _create_ticket_card(client, "CARD-A", "10000111", user.id, ticket_type="B")
    assert response.status_code == 200

    account = db_session.query(AccountModel).filter_by(account_id="CARD-A").first()
    assert account is not None
    assert account.credits == 1  # never the (decoy) submitted amount
    # invoice_number/ticket_type are NOT cached on the account — the ledger
    # below is the only place this is stored, read live for display.
    assert account.invoice_number is None
    assert account.ticket_type is None

    # The first ticket is recorded in the permanent ledger too, also at 1.
    ticket = db_session.query(LoadedTicketModel).filter_by(invoice_number="10000111").first()
    assert ticket is not None
    assert ticket.account_id == "CARD-A"
    assert ticket.credits == 1
    assert ticket.ticket_type == "B"

    # The badge in the returned panel is rendered live from that ledger row.
    assert "B-10000111" in response.text


def test_create_duplicate_invoice_is_blocked(client, db_session):
    user = _make_user(db_session)
    first = _create_ticket_card(client, "CARD-B1", "10000222", user.id)
    assert first.status_code == 200

    other_user = _make_user(db_session, "Juan", "Perez")
    second = _create_ticket_card(client, "CARD-B2", "10000222", other_user.id)
    assert second.status_code == 200
    assert "ya fue cargado" in second.text
    assert "CARD-B1" in second.text
    assert "Pablo Crux" in second.text

    # The second card must not have been created, nor a second ledger row.
    assert db_session.query(AccountModel).filter_by(account_id="CARD-B2").first() is None
    assert db_session.query(LoadedTicketModel).filter_by(invoice_number="10000222").count() == 1


def test_same_number_different_type_is_allowed(client, db_session):
    """The rule is on the (número, tipo) pair, not the número alone — the
    same 8-digit number can belong to two different voucher types."""
    user = _make_user(db_session)
    first = _create_ticket_card(client, "CARD-B3", "10000223", user.id, ticket_type="A")
    assert first.status_code == 200

    second = _create_ticket_card(client, "CARD-B4", "10000223", user.id, ticket_type="B")
    assert second.status_code == 200
    assert "ya fue cargado" not in second.text

    assert db_session.query(AccountModel).filter_by(account_id="CARD-B4").first() is not None
    assert db_session.query(LoadedTicketModel).filter_by(invoice_number="10000223").count() == 2

    # But the exact same pair again — still blocked.
    third = _create_ticket_card(client, "CARD-B5", "10000223", user.id, ticket_type="A")
    assert "ya fue cargado" in third.text
    assert db_session.query(AccountModel).filter_by(account_id="CARD-B5").first() is None


def test_load_ticket_same_number_different_type_is_allowed(client, db_session):
    user = _make_user(db_session)
    _create_ticket_card(client, "CARD-B6", "10000224", user.id, ticket_type="Y")

    response = _load_ticket(client, "CARD-B6", "10000224", ticket_type="R")
    assert response.status_code == 200
    assert "ya fue cargado" not in response.text

    account = db_session.query(AccountModel).filter_by(account_id="CARD-B6").first()
    assert account.credits == 2  # both tickets accepted
    assert db_session.query(LoadedTicketModel).filter_by(account_id="CARD-B6").count() == 2

    # Same (número, tipo) again — blocked.
    repeat = _load_ticket(client, "CARD-B6", "10000224", ticket_type="Y")
    assert "ya fue cargado" in repeat.text
    db_session.refresh(account)
    assert account.credits == 2  # unchanged


def test_duplicate_check_ignores_key_type(client, db_session):
    """invoice_number collisions only matter between ticket_carga cards."""
    user = _make_user(db_session)
    account = AccountModel(
        account_id="CARD-C1",
        status="active",
        expiration_date=utcnow() + datetime.timedelta(hours=24),
        credits=10,
        user_id=user.id,
        key_type="particulares",
        invoice_number=None,
    )
    db_session.add(account)
    db_session.commit()

    response = _create_ticket_card(client, "CARD-C2", "10000333", user.id)
    assert response.status_code == 200
    assert db_session.query(AccountModel).filter_by(account_id="CARD-C2").first() is not None


def test_create_ticket_rejects_wrong_digit_count(client, db_session):
    user = _make_user(db_session)

    too_short = _create_ticket_card(client, "CARD-X1", "1234567", user.id)  # 7 digits
    assert too_short.status_code == 200
    assert "8 dígitos" in too_short.text
    assert db_session.query(AccountModel).filter_by(account_id="CARD-X1").first() is None

    too_long = _create_ticket_card(client, "CARD-X2", "123456789", user.id)  # 9 digits
    assert too_long.status_code == 200
    assert "8 dígitos" in too_long.text
    assert db_session.query(AccountModel).filter_by(account_id="CARD-X2").first() is None


def test_create_ticket_rejects_invalid_ticket_type(client, db_session):
    user = _make_user(db_session)
    response = _create_ticket_card(client, "CARD-X3", "10000999", user.id, ticket_type="Z")
    assert response.status_code == 200
    assert "A, B, Y o R" in response.text
    assert db_session.query(AccountModel).filter_by(account_id="CARD-X3").first() is None


def test_edit_cannot_change_ticket_carga_credits(client, db_session):
    """Editing status/expiry/key_type still works, but for a ticket_carga
    card the submitted credits value is ignored — that balance can only move
    via ui_load_ticket (+1 per ticket)."""
    user = _make_user(db_session)
    _create_ticket_card(client, "CARD-D1", "10000444", user.id)

    response = client.post(
        "/ui/accounts/CARD-D1/edit",
        data={
            "status": "active",
            "expiration_date": (utcnow() + datetime.timedelta(hours=48)).isoformat(),
            "credits": 500,  # decoy — must be ignored
            "key_type": "ticket_carga",
        },
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    account = db_session.query(AccountModel).filter_by(account_id="CARD-D1").first()
    assert account.credits == 1  # unchanged from ticket creation, not 500
    ticket = db_session.query(LoadedTicketModel).filter_by(account_id="CARD-D1").first()
    assert ticket is not None and ticket.invoice_number == "10000444"
    assert db_session.query(LoadedTicketModel).filter_by(account_id="CARD-D1").count() == 1


def test_edit_can_change_credits_for_non_ticket_types(client, db_session):
    """The credits restriction is specific to ticket_carga — particulares
    and cuenta_corriente can still have their balance set via Editar."""
    user = _make_user(db_session)
    account = AccountModel(
        account_id="CARD-D2",
        status="active",
        expiration_date=utcnow() + datetime.timedelta(hours=24),
        credits=3,
        user_id=user.id,
        key_type="cuenta_corriente",
    )
    db_session.add(account)
    db_session.commit()

    response = client.post(
        "/ui/accounts/CARD-D2/edit",
        data={
            "status": "active",
            "expiration_date": (utcnow() + datetime.timedelta(hours=48)).isoformat(),
            "credits": 20,
            "key_type": "cuenta_corriente",
        },
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    db_session.refresh(account)
    assert account.credits == 20


def test_several_tickets_accumulate_onto_one_llave(client, db_session):
    """The scenario the whole feature is for: a client brings multiple
    tickets over time, each worth exactly 1 credit, all onto the same card."""
    user = _make_user(db_session)
    _create_ticket_card(client, "CARD-E1", "10000501", user.id, ticket_type="A")

    r2 = _load_ticket(client, "CARD-E1", "10000502", ticket_type="Y")
    assert r2.status_code == 200
    r3 = _load_ticket(client, "CARD-E1", "10000503", ticket_type="R")
    assert r3.status_code == 200

    account = db_session.query(AccountModel).filter_by(account_id="CARD-E1").first()
    assert account.credits == 3  # 1 per ticket, three tickets
    # invoice_number/ticket_type are never cached on the account — "most
    # recently loaded" is derived live from the ledger (see below and the
    # panel HTML assertion), not stored redundantly here.
    assert account.invoice_number is None
    assert account.ticket_type is None

    history = (
        db_session.query(LoadedTicketModel)
        .filter_by(account_id="CARD-E1")
        .order_by(LoadedTicketModel.invoice_number)
        .all()
    )
    assert [t.invoice_number for t in history] == ["10000501", "10000502", "10000503"]
    assert [t.credits for t in history] == [1, 1, 1]
    assert [t.ticket_type for t in history] == ["A", "Y", "R"]

    # The panel's badge shows the most recently loaded ticket, computed live
    # from the ledger's most recent row (created_at desc) — not a cached field.
    assert "R-10000503" in r3.text


def test_load_ticket_already_used_on_another_card_is_blocked(client, db_session):
    user = _make_user(db_session)
    _create_ticket_card(client, "CARD-F1", "10000601", user.id)
    _create_ticket_card(client, "CARD-F2", "10000602", user.id)

    response = _load_ticket(client, "CARD-F2", "10000601")
    assert response.status_code == 200
    assert "ya fue cargado" in response.text
    assert "CARD-F1" in response.text

    # CARD-F2's balance and history are untouched — the load was rejected.
    card_f2 = db_session.query(AccountModel).filter_by(account_id="CARD-F2").first()
    assert card_f2.credits == 1
    assert db_session.query(LoadedTicketModel).filter_by(account_id="CARD-F2").count() == 1


def test_load_ticket_rejects_non_ticket_carga_card(client, db_session):
    user = _make_user(db_session)
    account = AccountModel(
        account_id="CARD-G1",
        status="active",
        expiration_date=utcnow() + datetime.timedelta(hours=24),
        credits=10,
        user_id=user.id,
        key_type="particulares",
    )
    db_session.add(account)
    db_session.commit()

    response = _load_ticket(client, "CARD-G1", "10000700")
    assert response.status_code == 400


def test_load_ticket_rejects_wrong_digit_count_and_invalid_type(client, db_session):
    user = _make_user(db_session)
    _create_ticket_card(client, "CARD-X4", "10000800", user.id)

    bad_length = _load_ticket(client, "CARD-X4", "12345", ticket_type="A")
    assert bad_length.status_code == 200
    assert "8 dígitos" in bad_length.text

    bad_type = _load_ticket(client, "CARD-X4", "10000801", ticket_type="Q")
    assert bad_type.status_code == 200
    assert "A, B, Y o R" in bad_type.text

    # Neither bad request actually loaded a ticket.
    account = db_session.query(AccountModel).filter_by(account_id="CARD-X4").first()
    assert account.credits == 1
    assert db_session.query(LoadedTicketModel).filter_by(account_id="CARD-X4").count() == 1


def test_generic_payment_works_for_particulares_and_cuenta_corriente(client, db_session):
    """Pago (cash) and cuenta corriente are the only ways to add an arbitrary
    amount — verified here via the generic /ui/accounts/{id}/recharge flow."""
    user = _make_user(db_session)
    particular = AccountModel(
        account_id="CARD-H1",
        status="active",
        expiration_date=utcnow() + datetime.timedelta(hours=24),
        credits=3,
        user_id=user.id,
        key_type="particulares",
    )
    cuenta_corriente = AccountModel(
        account_id="CARD-H2",
        status="active",
        expiration_date=utcnow() + datetime.timedelta(hours=24),
        credits=3,
        user_id=user.id,
        key_type="cuenta_corriente",
    )
    db_session.add_all([particular, cuenta_corriente])
    db_session.commit()

    for account_id in ("CARD-H1", "CARD-H2"):
        response = client.post(
            f"/ui/accounts/{account_id}/recharge",
            data={"amount": 5},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200

    db_session.refresh(particular)
    db_session.refresh(cuenta_corriente)
    assert particular.credits == 8
    assert cuenta_corriente.credits == 8


def test_generic_payment_also_allowed_on_ticket_carga(client, db_session):
    """Pago (cash) is available on every key_type, including ticket_carga —
    a client may show up without their voucher (or without cuenta
    corriente) and still needs to pay to get in. This is on top of, not
    instead of, the +1-per-ticket ledger channel."""
    user = _make_user(db_session)
    _create_ticket_card(client, "CARD-H3", "10000901", user.id)

    response = client.post(
        "/ui/accounts/CARD-H3/recharge",
        data={"amount": 5},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    account = db_session.query(AccountModel).filter_by(account_id="CARD-H3").first()
    assert account.credits == 6  # 1 from the ticket + 5 from the cash payment

    # The ticket ledger/history is untouched by the cash payment.
    assert db_session.query(LoadedTicketModel).filter_by(account_id="CARD-H3").count() == 1


def test_create_particulares_card_ignores_blank_ticket_fields(client, db_session):
    """The real browser form keeps the (hidden) invoice_number/ticket_type
    inputs in the DOM even for particulares/cuenta_corriente, so they still
    get submitted — empty and "A" respectively. This mirrors that exact
    request shape to make sure it doesn't break account creation."""
    user = _make_user(db_session)
    response = client.post(
        "/ui/accounts/create",
        data={
            "account_id": "CARD-Y1",
            "status": "active",
            "expiration_date": (utcnow() + datetime.timedelta(hours=24)).isoformat(),
            "credits": 10,
            "user_id": user.id,
            "key_type": "particulares",
            "invoice_number": "",
            "ticket_type": "A",
        },
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    account = db_session.query(AccountModel).filter_by(account_id="CARD-Y1").first()
    assert account is not None
    assert account.credits == 10
    assert account.invoice_number is None
    assert account.ticket_type is None


def test_leading_zero_ticket_number_is_preserved(client, db_session):
    """The user's own example: a ticket número can start with 0 (e.g.
    "00012345" or "00004567"), and that leading zero is significant — it must
    survive storage/retrieval exactly, not be coerced into an integer."""
    user = _make_user(db_session)
    response = _create_ticket_card(client, "CARD-Z1", "00012345", user.id, ticket_type="A")
    assert response.status_code == 200

    account = db_session.query(AccountModel).filter_by(account_id="CARD-Z1").first()
    assert account is not None
    assert "00012345" in response.text

    ticket = db_session.query(LoadedTicketModel).filter_by(account_id="CARD-Z1").first()
    assert ticket.invoice_number == "00012345"

    # "00012345" and "12345" (7 digits, would-be same integer minus zero) are
    # different strings — "12345" is even rejected outright as too short.
    rejected = _create_ticket_card(client, "CARD-Z2", "12345", user.id, ticket_type="A")
    assert "8 dígitos" in rejected.text

    # A second, distinct leading-zero ticket on the same card via load-ticket.
    loaded = _load_ticket(client, "CARD-Z1", "00004567", ticket_type="B")
    assert loaded.status_code == 200
    assert "ya fue cargado" not in loaded.text
    assert "00004567" in loaded.text
    db_session.refresh(account)
    assert account.credits == 2

    # And the exact same leading-zero pair again is blocked, proving the
    # duplicate check compares the full zero-padded string, not an int value.
    dup = _load_ticket(client, "CARD-Z1", "00004567", ticket_type="B")
    assert "ya fue cargado" in dup.text


def test_badge_reflects_live_ledger_after_manual_row_deletion(client, db_session):
    """Regression test for a reported bug: an admin deleted a ticket row
    directly from the database (outside the app — there is no delete-ticket
    feature by design), and the panel kept showing the deleted ticket's
    number in the card's badge even though "Historial de tickets" correctly
    showed it as gone. That happened because the badge used to be read from a
    cached field on the account row instead of the ledger. The badge must now
    be computed live from the ledger, same as the history, so both are
    always consistent with each other and with the actual ledger contents."""
    user = _make_user(db_session)
    _create_ticket_card(client, "CARD-W1", "10000701", user.id, ticket_type="R")

    # Sanity check: right after loading, the panel shows the ticket.
    panel = client.get(f"/ui/users/{user.id}/detail", headers={"HX-Request": "true"})
    assert panel.status_code == 200
    assert "R-10000701" in panel.text
    assert "Todavía no se cargó ningún ticket" not in panel.text

    # Simulate an admin manually deleting the ledger row straight from the
    # database (not through the app).
    ticket = db_session.query(LoadedTicketModel).filter_by(account_id="CARD-W1").first()
    db_session.delete(ticket)
    db_session.commit()

    # Reopening the panel must not show the deleted ticket anywhere —
    # neither in the badge nor in the (now genuinely empty) history.
    panel_after = client.get(f"/ui/users/{user.id}/detail", headers={"HX-Request": "true"})
    assert panel_after.status_code == 200
    assert "R-10000701" not in panel_after.text
    assert "10000701" not in panel_after.text
    assert "Todavía no se cargó ningún ticket" in panel_after.text

    # The card's credit balance is untouched — deleting a ledger row is a
    # raw database edit the app has no knowledge of, not an "undo" action.
    account = db_session.query(AccountModel).filter_by(account_id="CARD-W1").first()
    assert account.credits == 1
