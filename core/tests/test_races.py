"""Races only a real database can show. SQLite serialises every write, so these are
skipped there; CI runs them against Postgres, which is what production uses.

Each test starts two threads behind a barrier so both reach the database together,
each on its own connection, the way two gunicorn workers would.
"""

import threading
from types import SimpleNamespace

import pytest
from django.db import connection

from core import fulfilment, payments
from core.models import Order, Product, StripeEvent
from core.tests.factories import make_product
from core.tests.test_webhook import paid_session

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="needs Postgres row locks"),
]


def completed(event_id: str, session_id: str):
    return SimpleNamespace(
        id=event_id,
        type="checkout.session.completed",
        data=SimpleNamespace(object=SimpleNamespace(id=session_id)),
    )


def race(*events):
    """Process the events concurrently; returns what each thread raised, if anything."""
    barrier = threading.Barrier(len(events))
    errors: list[BaseException] = []

    def run(event):
        from django.db import connection as thread_connection

        try:
            barrier.wait()
            fulfilment.handle_event(event)
        except BaseException as exc:  # surfaced to the test below
            errors.append(exc)
        finally:
            thread_connection.close()

    threads = [threading.Thread(target=run, args=(e,)) for e in events]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return errors


@pytest.fixture
def sessions(monkeypatch):
    found: dict = {}
    monkeypatch.setattr(payments, "retrieve_checkout_session", lambda sid: found[sid])
    return found


@pytest.mark.parametrize("attempt", range(5))
def test_two_customers_paying_for_the_last_unit_never_oversell(sessions, attempt):
    kettle = make_product(stock=1)
    sessions["cs_a"] = paid_session("cs_a", [(kettle, 1)])
    sessions["cs_b"] = paid_session("cs_b", [(kettle, 1)])

    assert race(completed("evt_a", "cs_a"), completed("evt_b", "cs_b")) == []

    statuses = sorted(Order.objects.values_list("status", flat=True))
    assert statuses == [Order.Status.NEEDS_REFUND, Order.Status.PAID]
    assert Product.objects.get(pk=kettle.pk).stock == 0


@pytest.mark.parametrize("attempt", range(5))
def test_the_same_event_delivered_twice_at_once_creates_one_order(sessions, attempt):
    """Both deliveries pass the "seen it?" check before either commits; the unique
    constraint on the event id is what stops the second one."""
    kettle = make_product(stock=5)
    sessions["cs_a"] = paid_session("cs_a", [(kettle, 1)])

    assert race(completed("evt_a", "cs_a"), completed("evt_a", "cs_a")) == []

    assert Order.objects.count() == 1
    assert StripeEvent.objects.count() == 1
    assert Product.objects.get(pk=kettle.pk).stock == 4
