import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def get_twilio_client():
    sid = os.environ.get('TWILIO_ACCOUNT_SID', '')
    token = os.environ.get('TWILIO_AUTH_TOKEN', '')
    if not sid or not token:
        logger.warning("Twilio credentials not configured")
        return None
    try:
        from twilio.rest import Client
        return Client(sid, token)
    except Exception as e:
        logger.error(f"Failed to create Twilio client: {e}")
        return None

def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.startswith("+91"):
        return phone
    if phone.startswith("91") and len(phone) == 12:
        return f"+{phone}"
    if phone.startswith("0"):
        phone = phone[1:]
    if len(phone) == 10 and phone.isdigit():
        return f"+91{phone}"
    if phone.startswith("+"):
        return phone
    return f"+91{phone}"

def send_whatsapp_template(recipient_number: str, content_sid: str, content_variables: dict):
    client = get_twilio_client()
    if not client:
        return {"success": False, "error": "Twilio client not configured", "message_sid": None}

    if not content_sid:
        return {"success": False, "error": "Content SID not configured", "message_sid": None}

    whatsapp_to = f"whatsapp:{normalize_phone(recipient_number)}"
    messaging_service_sid = os.environ.get('TWILIO_MESSAGING_SERVICE_SID', '')
    whatsapp_from = os.environ.get('TWILIO_WHATSAPP_FROM', '')

    try:
        kwargs = {
            "to": whatsapp_to,
            "content_sid": content_sid,
            "content_variables": json.dumps(content_variables),
        }
        if messaging_service_sid:
            kwargs["messaging_service_sid"] = messaging_service_sid
        elif whatsapp_from:
            kwargs["from_"] = whatsapp_from
        else:
            return {"success": False, "error": "No messaging service or from number configured", "message_sid": None}

        message = client.messages.create(**kwargs)
        logger.info(f"WhatsApp sent to {whatsapp_to}, SID: {message.sid}")
        return {"success": True, "message_sid": message.sid, "error": None}
    except Exception as e:
        logger.error(f"WhatsApp send failed to {whatsapp_to}: {e}")
        return {"success": False, "error": str(e), "message_sid": None}

def send_registration_confirmation(recipient_number: str, first_name: str, event_name: str,
                                     event_date: str, event_time: str, venue_area: str, status: str):
    content_sid = os.environ.get('TWILIO_CONTENT_SID_REG_CONFIRM', '')
    variables = {"1": first_name, "2": event_name, "3": event_date, "4": event_time, "5": venue_area, "6": status}
    return send_whatsapp_template(recipient_number, content_sid, variables)

def send_event_reminder(recipient_number: str, first_name: str, event_name: str,
                        event_date: str, event_time: str, venue_area: str, dress_code: str):
    content_sid = os.environ.get('TWILIO_CONTENT_SID_EVENT_REMINDER', '')
    variables = {"1": first_name, "2": event_name, "3": event_date, "4": event_time, "5": venue_area, "6": dress_code}
    return send_whatsapp_template(recipient_number, content_sid, variables)

def send_checkin_details(recipient_number: str, first_name: str, event_name: str,
                         venue_name: str, address: str, reporting_time: str, booking_status: str):
    content_sid = os.environ.get('TWILIO_CONTENT_SID_CHECKIN_DETAILS', '')
    variables = {"1": first_name, "2": event_name, "3": venue_name, "4": address, "5": reporting_time, "6": booking_status}
    return send_whatsapp_template(recipient_number, content_sid, variables)
