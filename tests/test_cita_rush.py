import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Health check
def test_api_root():
    r = requests.get(f"{BASE_URL}/api/")
    assert r.status_code == 200

# Events
def test_get_events_returns_6():
    r = requests.get(f"{BASE_URL}/api/events")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 6

def test_get_event_by_id():
    r = requests.get(f"{BASE_URL}/api/events")
    events = r.json()
    event_id = events[0]['id']
    r2 = requests.get(f"{BASE_URL}/api/events/{event_id}")
    assert r2.status_code == 200
    assert r2.json()['id'] == event_id

def test_get_event_not_found():
    r = requests.get(f"{BASE_URL}/api/events/nonexistent-id")
    assert r.status_code == 404

# Bookings
def test_create_booking():
    events = requests.get(f"{BASE_URL}/api/events").json()
    event_id = events[0]['id']
    payload = {
        "event_id": event_id,
        "name": "TEST_User Booking",
        "email": f"TEST_{uuid.uuid4()}@example.com",
        "phone": "9876543210",
        "age": 28
    }
    r = requests.post(f"{BASE_URL}/api/bookings", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data['event_id'] == event_id
    assert data['name'] == payload['name']
    assert 'id' in data

def test_create_booking_invalid_event():
    payload = {
        "event_id": "nonexistent-event-id",
        "name": "TEST_User",
        "email": "test@example.com",
        "phone": "9876543210"
    }
    r = requests.post(f"{BASE_URL}/api/bookings", json=payload)
    assert r.status_code == 404

# Waitlist
def test_create_waitlist():
    payload = {
        "name": "TEST_Waitlist User",
        "email": f"TEST_{uuid.uuid4()}@waitlist.com",
        "phone": "9876543210",
        "age": 25,
        "preferred_area": "Koregaon Park"
    }
    r = requests.post(f"{BASE_URL}/api/waitlist", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data['name'] == payload['name']
    assert 'id' in data

def test_create_waitlist_duplicate_email():
    email = f"TEST_dup_{uuid.uuid4()}@waitlist.com"
    payload = {"name": "TEST_Dup", "email": email, "phone": "9876543210"}
    requests.post(f"{BASE_URL}/api/waitlist", json=payload)
    r = requests.post(f"{BASE_URL}/api/waitlist", json=payload)
    assert r.status_code == 400

# Partners
def test_create_partner_inquiry():
    payload = {
        "venue_name": "TEST_Venue",
        "contact_name": "TEST_Contact",
        "email": f"TEST_{uuid.uuid4()}@venue.com",
        "phone": "9876543210",
        "message": "Interested in partnership"
    }
    r = requests.post(f"{BASE_URL}/api/partners", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data['venue_name'] == payload['venue_name']
    assert 'id' in data

# Stats
def test_get_stats():
    r = requests.get(f"{BASE_URL}/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert 'events' in data
    assert 'bookings' in data
    assert 'waitlist' in data
    assert 'partner_inquiries' in data
    assert data['events'] >= 6
