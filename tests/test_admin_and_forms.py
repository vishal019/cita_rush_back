"""Backend tests for Cita Rush admin panel and expanded form fields"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
ADMIN_PASSWORD = "citarush_admin_2025"

@pytest.fixture(scope="module")
def admin_token():
    resp = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD})
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    return resp.json()["token"]

@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}

@pytest.fixture(scope="module")
def event_id():
    """Get first published event id"""
    resp = requests.get(f"{BASE_URL}/api/events")
    events = resp.json()
    if events:
        return events[0]["id"]
    pytest.skip("No events in DB")

# ─── Admin Auth ───────────────────────────────────────────────────────

class TestAdminAuth:
    def test_login_correct_password(self):
        resp = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert isinstance(data["token"], str)
        assert len(data["token"]) > 0

    def test_login_wrong_password(self):
        resp = requests.post(f"{BASE_URL}/api/admin/login", json={"password": "wrongpassword"})
        assert resp.status_code == 401

    def test_dashboard_requires_auth(self):
        resp = requests.get(f"{BASE_URL}/api/admin/dashboard")
        assert resp.status_code == 401

# ─── Admin Dashboard ──────────────────────────────────────────────────

class TestAdminDashboard:
    def test_dashboard_returns_stats(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/admin/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "upcomingEvents" in data
        assert "totalBookings" in data
        assert "totalWaitlist" in data
        assert "todayRegistrations" in data
        assert "whatsappSent" in data
        assert "whatsappFailed" in data

# ─── Admin Events ─────────────────────────────────────────────────────

class TestAdminEvents:
    def test_list_events(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/admin/events", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        if data:
            assert "bookingCount" in data[0]
            assert "waitlistCount" in data[0]

    def test_create_event(self, auth_headers):
        payload = {
            "title": "TEST_Event",
            "venueArea": "Koregaon Park",
            "eventDate": "2026-03-15",
            "eventTime": "7:00 PM",
            "ageBand": "25-35"
        }
        resp = requests.post(f"{BASE_URL}/api/admin/events", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "TEST_Event"
        assert "id" in data
        # Cleanup
        requests.delete(f"{BASE_URL}/api/admin/events/{data['id']}", headers=auth_headers)

    def test_update_event(self, auth_headers, event_id):
        resp = requests.put(f"{BASE_URL}/api/admin/events/{event_id}",
                            json={"description": "Updated desc"}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Updated desc"

    def test_set_hero_event(self, auth_headers, event_id):
        resp = requests.put(f"{BASE_URL}/api/admin/events/{event_id}/hero", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data

# ─── Booking with expanded fields + phone normalization ───────────────

class TestBookings:
    created_booking_id = None

    def test_create_booking_expanded_fields(self, auth_headers, event_id):
        payload = {
            "fullName": "TEST_User One",
            "email": "testuser_booking@example.com",
            "phoneNumber": "9876543210",  # should normalize to +919876543210
            "whatsappOptIn": False,
            "gender": "male",
            "age": 28,
            "city": "Pune",
            "eventId": event_id
        }
        resp = requests.post(f"{BASE_URL}/api/bookings", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["fullName"] == "TEST_User One"
        TestBookings.created_booking_id = data["id"]

    def test_phone_normalization(self, auth_headers):
        # Verify phone was normalized in DB via admin endpoint
        resp = requests.get(f"{BASE_URL}/api/admin/bookings", headers=auth_headers)
        assert resp.status_code == 200
        bookings = resp.json()
        # Find our test booking
        test_booking = next((b for b in bookings if b.get("email") == "testuser_booking@example.com"), None)
        if test_booking:
            assert test_booking["phoneNumber"] == "+919876543210", f"Phone not normalized: {test_booking['phoneNumber']}"

    def test_list_bookings(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/admin/bookings", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_update_booking_status(self, auth_headers):
        if not TestBookings.created_booking_id:
            pytest.skip("No booking created")
        resp = requests.put(
            f"{BASE_URL}/api/admin/bookings/{TestBookings.created_booking_id}/status",
            json={"status": "confirmed"}, headers=auth_headers
        )
        assert resp.status_code == 200

# ─── Waitlist ─────────────────────────────────────────────────────────

class TestWaitlist:
    created_entry_id = None

    def test_create_waitlist_expanded_fields(self):
        payload = {
            "fullName": "TEST_Waitlist User",
            "email": "testwaitlist_unique123@example.com",
            "phoneNumber": "9123456780",
            "whatsappOptIn": False,
            "gender": "female",
            "age": 26,
            "city": "Pune",
            "preferredArea": "Baner",
            "instagramHandle": "@test_user",
            "linkedinProfile": "linkedin.com/in/testuser"
        }
        resp = requests.post(f"{BASE_URL}/api/waitlist", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["waitlistStatus"] == "pending"
        TestWaitlist.created_entry_id = data["id"]

    def test_list_waitlist(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/admin/waitlist", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_update_waitlist_status(self, auth_headers):
        if not TestWaitlist.created_entry_id:
            pytest.skip("No waitlist entry created")
        resp = requests.put(
            f"{BASE_URL}/api/admin/waitlist/{TestWaitlist.created_entry_id}/status",
            json={"status": "approved"}, headers=auth_headers
        )
        assert resp.status_code == 200

# ─── WhatsApp Logs ────────────────────────────────────────────────────

class TestWhatsAppLogs:
    def test_get_whatsapp_logs(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/admin/whatsapp-logs", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
