"""Milestone 0 smoke tests: the app boots, serves a page, and reports health."""
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_home_page_renders(client):
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert b"shopfront" in response.content


def test_healthz_reports_ok(client):
    """No database access, so this stays green even if the database is unreachable."""
    response = client.get(reverse("healthz"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_admin_redirects_anonymous_users_to_login(client):
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]
