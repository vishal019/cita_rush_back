from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, uuid, io, csv, base64
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone
from whatsapp_service import (
    normalize_phone, send_registration_confirmation,
    send_event_reminder, send_checkin_details, send_whatsapp_template
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

UPLOADS_DIR = ROOT_DIR / 'uploads'
UPLOADS_DIR.mkdir(exist_ok=True)

mongo_url = os.environ['MONGO_URL']
import certifi
client = AsyncIOMotorClient(mongo_url, tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'citarush_admin_2025')

# ─── Admin Auth ───────────────────────────────────────────────────────
async def verify_admin(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.split(" ")[1]
    session = await db.admin_sessions.find_one({"token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return session

# ─── Pydantic Models ─────────────────────────────────────────────────
class BookingCreate(BaseModel):
    fullName: str
    email: str
    phoneNumber: str
    whatsappNumber: Optional[str] = ""
    whatsappOptIn: bool = False
    gender: Optional[str] = "male"
    age: Optional[int] = None
    city: Optional[str] = "Pune"
    eventId: str
    utrNumber: str
    realtimePhoto: str
    uploadedPhoto: str
    notes: Optional[str] = ""

class WaitlistCreate(BaseModel):
    fullName: str
    email: str
    phoneNumber: str
    whatsappNumber: Optional[str] = ""
    whatsappOptIn: bool = False
    gender: Optional[str] = "female"
    age: Optional[int] = None
    city: Optional[str] = "Pune"
    instagramHandle: Optional[str] = ""
    linkedinProfile: Optional[str] = ""
    preferredArea: Optional[str] = ""
    realtimePhoto: Optional[str] = ""
    uploadedPhoto: Optional[str] = ""
    notes: Optional[str] = ""

class EventCreate(BaseModel):
    title: str
    venueName: Optional[str] = ""
    venueArea: str
    fullAddress: Optional[str] = ""
    city: Optional[str] = "Pune"
    eventDate: str
    eventTime: str
    reportingTime: Optional[str] = ""
    ageBand: str
    miniDatesPerGuest: Optional[int] = 6
    avgMatches: Optional[int] = 3
    dressCode: Optional[str] = "Smart casual"
    totalMaleSpots: Optional[int] = 12
    totalFemaleSpots: Optional[int] = 12
    eventType: Optional[str] = "speed-dating"
    eventStatus: Optional[str] = "published"
    tags: Optional[List[str]] = []
    heroCardVisible: Optional[bool] = False
    theme: Optional[str] = ""
    description: Optional[str] = ""

class EventUpdate(BaseModel):
    title: Optional[str] = None
    venueName: Optional[str] = None
    venueArea: Optional[str] = None
    fullAddress: Optional[str] = None
    city: Optional[str] = None
    eventDate: Optional[str] = None
    eventTime: Optional[str] = None
    reportingTime: Optional[str] = None
    ageBand: Optional[str] = None
    miniDatesPerGuest: Optional[int] = None
    avgMatches: Optional[int] = None
    dressCode: Optional[str] = None
    totalMaleSpots: Optional[int] = None
    totalFemaleSpots: Optional[int] = None
    eventType: Optional[str] = None
    eventStatus: Optional[str] = None
    tags: Optional[List[str]] = None
    heroCardVisible: Optional[bool] = None
    theme: Optional[str] = None
    description: Optional[str] = None

class PartnerInquiryCreate(BaseModel):
    venue_name: str
    contact_name: str
    email: str
    phone: str
    message: Optional[str] = ""

class AdminLogin(BaseModel):
    password: str

class StatusUpdate(BaseModel):
    status: str

class ManualWhatsApp(BaseModel):
    recipientNumber: str
    templateType: str
    variables: Optional[dict] = {}

# ─── Helper: Log WhatsApp ────────────────────────────────────────────
async def log_whatsapp(user_type, related_id, recipient, template_type, content_sid, variables, result):
    doc = {
        "id": str(uuid.uuid4()),
        "userType": user_type,
        "relatedRecordId": related_id,
        "recipientNumber": recipient,
        "templateType": template_type,
        "contentSid": content_sid or "",
        "contentVariables": str(variables),
        "messageSid": result.get("message_sid") or "",
        "sendStatus": "sent" if result.get("success") else "failed",
        "errorMessage": result.get("error") or "",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "sentAt": datetime.now(timezone.utc).isoformat() if result.get("success") else "",
    }
    await db.whatsapp_logs.insert_one(doc)

# ═══════════════════════ PUBLIC ROUTES ═══════════════════════════════

@api.get("/")
async def root():
    return {"message": "Cita Rush API"}

# ─── Public Events ────────────────────────────────────────────────────
@api.get("/events")
async def list_events():
    events = await db.events.find({"eventStatus": {"$in": ["published", "sold_out"]}}, {"_id": 0}).to_list(100)
    result = []
    for e in events:
        spots_taken_male = await db.bookings.count_documents({"eventId": e["id"], "bookingStatus": {"$ne": "cancelled"}})
        spots_taken_female = await db.waitlist.count_documents({"eventId": e["id"], "waitlistStatus": {"$in": ["approved", "confirmed"]}})
        e["spotsLeft"] = max(0, e.get("totalMaleSpots", 12) - spots_taken_male)
        e["spotsLeftFemale"] = max(0, e.get("totalFemaleSpots", 12) - spots_taken_female)
        # Backward compat fields
        e["name"] = e.get("title", "")
        e["area"] = e.get("venueArea", "")
        e["date"] = e.get("eventDate", "")
        e["time"] = e.get("eventTime", "")
        e["age_band"] = e.get("ageBand", "")
        e["spots_total"] = e.get("totalMaleSpots", 12)
        e["spots_taken"] = spots_taken_male
        result.append(e)
    return result

@api.get("/events/hero")
async def get_hero_event():
    event = await db.events.find_one({"heroCardVisible": True, "eventStatus": "published"}, {"_id": 0})
    if not event:
        event = await db.events.find_one({"eventStatus": "published"}, {"_id": 0})
    if event:
        spots_taken = await db.bookings.count_documents({"eventId": event["id"], "bookingStatus": {"$ne": "cancelled"}})
        event["spotsLeft"] = max(0, event.get("totalMaleSpots", 12) - spots_taken)
        event["name"] = event.get("title", "")
        event["area"] = event.get("venueArea", "")
        event["date"] = event.get("eventDate", "")
        event["time"] = event.get("eventTime", "")
        event["age_band"] = event.get("ageBand", "")
        event["spots_total"] = event.get("totalMaleSpots", 12)
        event["spots_taken"] = spots_taken
    return event

@api.get("/events/{event_id}")
async def get_event(event_id: str):
    event = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

# ─── Public Bookings ──────────────────────────────────────────────────
@api.post("/bookings")
async def create_booking(data: BookingCreate):
    event = await db.events.find_one({"id": data.eventId}, {"_id": 0})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    phone = normalize_phone(data.phoneNumber)
    wa_number = normalize_phone(data.whatsappNumber) if data.whatsappNumber else phone
    first_name = data.fullName.split()[0] if data.fullName else ""

    try:
        def save_image(b64_str):
            header, encoded = b64_str.split(",", 1) if "," in b64_str else ("", b64_str)
            ext = "png" if "image/png" in header else "jpeg"
            image_data = base64.b64decode(encoded)
            filename = f"{uuid.uuid4()}.{ext}"
            filepath = UPLOADS_DIR / filename
            with open(filepath, "wb") as f:
                f.write(image_data)
            return f"/uploads/{filename}"

        realtime_url = save_image(data.realtimePhoto)
        uploaded_url = save_image(data.uploadedPhoto)
    except Exception as e:
        logger.error(f"Failed to process image: {e}")
        raise HTTPException(status_code=400, detail="Invalid photo data. Ensure it is a valid base64 image.")

    booking = {
        "id": str(uuid.uuid4()),
        "fullName": data.fullName,
        "firstName": first_name,
        "email": data.email,
        "phoneNumber": phone,
        "whatsappNumber": wa_number,
        "whatsappOptIn": data.whatsappOptIn,
        "gender": data.gender or "male",
        "age": data.age,
        "city": data.city or "Pune",
        "eventId": data.eventId,
        "eventName": event.get("title", ""),
        "venueArea": event.get("venueArea", ""),
        "venueName": event.get("venueName", ""),
        "eventDate": event.get("eventDate", ""),
        "eventTime": event.get("eventTime", ""),
        "ageBand": event.get("ageBand", ""),
        "bookingStatus": "reserved",
        "paymentStatus": "pending",
        "paymentReference": "",
        "utrNumber": data.utrNumber,
        "realtimePhotoUrl": realtime_url,
        "uploadedPhotoUrl": uploaded_url,
        "source": "website",
        "notes": data.notes or "",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.bookings.insert_one(booking)

    wa_result = {"success": False, "error": "WhatsApp opt-in not provided"}
    if data.whatsappOptIn:
        wa_result = send_registration_confirmation(
            wa_number, first_name, event.get("title", ""),
            event.get("eventDate", ""), event.get("eventTime", ""),
            event.get("venueArea", ""), "Reserved"
        )
        await log_whatsapp("booking", booking["id"], wa_number, "registration_confirmation",
                           os.environ.get('TWILIO_CONTENT_SID_REG_CONFIRM', ''),
                           {"1": first_name, "2": event.get("title", "")}, wa_result)

    return {
        "id": booking["id"], "fullName": booking["fullName"], "email": booking["email"],
        "bookingStatus": booking["bookingStatus"], "eventName": booking["eventName"],
        "whatsappSent": wa_result.get("success", False),
    }

# ─── Public Waitlist ──────────────────────────────────────────────────
@api.post("/waitlist")
async def create_waitlist(data: WaitlistCreate):
    phone = normalize_phone(data.phoneNumber)
    wa_number = normalize_phone(data.whatsappNumber) if data.whatsappNumber else phone
    first_name = data.fullName.split()[0] if data.fullName else ""

    existing = await db.waitlist.find_one({"email": data.email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="This email is already on the waitlist")

    try:
        def save_image(b64_str):
            if not b64_str:
                return ""
            header, encoded = b64_str.split(",", 1) if "," in b64_str else ("", b64_str)
            ext = "png" if "image/png" in header else "jpeg"
            image_data = base64.b64decode(encoded)
            filename = f"{uuid.uuid4()}.{ext}"
            filepath = UPLOADS_DIR / filename
            with open(filepath, "wb") as f:
                f.write(image_data)
            return f"/uploads/{filename}"

        realtime_url = save_image(data.realtimePhoto)
        uploaded_url = save_image(data.uploadedPhoto)
    except Exception as e:
        logger.error(f"Failed to process image: {e}")
        raise HTTPException(status_code=400, detail="Invalid photo data. Ensure it is a valid base64 image.")

    # If no eventId, create a general waitlist entry
    event = None
    if data.eventId if hasattr(data, 'eventId') else False:
        event = await db.events.find_one({"id": data.eventId}, {"_id": 0})

    entry = {
        "id": str(uuid.uuid4()),
        "fullName": data.fullName,
        "firstName": first_name,
        "email": data.email,
        "phoneNumber": phone,
        "whatsappNumber": wa_number,
        "whatsappOptIn": data.whatsappOptIn,
        "gender": data.gender or "female",
        "age": data.age,
        "city": data.city or "Pune",
        "instagramHandle": data.instagramHandle or "",
        "linkedinProfile": data.linkedinProfile or "",
        "eventId": event["id"] if event else "",
        "eventName": event.get("title", "") if event else "",
        "venueArea": event.get("venueArea", "") if event else (data.preferredArea or ""),
        "eventDate": event.get("eventDate", "") if event else "",
        "eventTime": event.get("eventTime", "") if event else "",
        "ageBand": event.get("ageBand", "") if event else "",
        "waitlistStatus": "pending",
        "realtimePhotoUrl": realtime_url,
        "uploadedPhotoUrl": uploaded_url,
        "notes": data.notes or "",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.waitlist.insert_one(entry)

    wa_result = {"success": False, "error": "WhatsApp opt-in not provided"}
    if data.whatsappOptIn:
        wa_result = send_registration_confirmation(
            wa_number, first_name, event.get("title", "Cita Rush Event") if event else "Cita Rush Event",
            event.get("eventDate", "TBA") if event else "TBA",
            event.get("eventTime", "TBA") if event else "TBA",
            event.get("venueArea", data.preferredArea or "Pune") if event else (data.preferredArea or "Pune"),
            "Waitlisted"
        )
        await log_whatsapp("waitlist", entry["id"], wa_number, "registration_confirmation",
                           os.environ.get('TWILIO_CONTENT_SID_REG_CONFIRM', ''),
                           {"1": first_name}, wa_result)

    return {
        "id": entry["id"], "fullName": entry["fullName"], "email": entry["email"],
        "waitlistStatus": entry["waitlistStatus"],
        "whatsappSent": wa_result.get("success", False),
    }

# ─── Public Partners ──────────────────────────────────────────────────
@api.post("/partners")
async def create_partner_inquiry(data: PartnerInquiryCreate):
    inquiry = {
        "id": str(uuid.uuid4()),
        "venue_name": data.venue_name, "contact_name": data.contact_name,
        "email": data.email, "phone": data.phone, "message": data.message or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.partner_inquiries.insert_one(inquiry)
    return {"id": inquiry["id"], "venue_name": inquiry["venue_name"]}

@api.get("/partners")
async def list_partner_inquiries():
    return await db.partner_inquiries.find({}, {"_id": 0}).to_list(1000)

# ═══════════════════════ ADMIN ROUTES ════════════════════════════════

@api.post("/admin/login")
async def admin_login(data: AdminLogin):
    if data.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
    token = str(uuid.uuid4())
    await db.admin_sessions.insert_one({"token": token, "createdAt": datetime.now(timezone.utc).isoformat()})
    return {"token": token}

@api.get("/admin/dashboard")
async def admin_dashboard(_=Depends(verify_admin)):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    upcoming = await db.events.count_documents({"eventStatus": {"$in": ["published", "sold_out"]}})
    total_bookings = await db.bookings.count_documents({})
    total_waitlist = await db.waitlist.count_documents({})
    today_bookings = await db.bookings.count_documents({"createdAt": {"$regex": f"^{now_iso}"}})
    today_waitlist = await db.waitlist.count_documents({"createdAt": {"$regex": f"^{now_iso}"}})
    wa_sent = await db.whatsapp_logs.count_documents({"sendStatus": "sent"})
    wa_failed = await db.whatsapp_logs.count_documents({"sendStatus": "failed"})
    return {
        "upcomingEvents": upcoming, "totalBookings": total_bookings,
        "totalWaitlist": total_waitlist, "todayRegistrations": today_bookings + today_waitlist,
        "whatsappSent": wa_sent, "whatsappFailed": wa_failed,
    }

# ─── Admin Events ─────────────────────────────────────────────────────
@api.get("/admin/events")
async def admin_list_events(_=Depends(verify_admin)):
    events = await db.events.find({}, {"_id": 0}).to_list(100)
    for e in events:
        e["bookingCount"] = await db.bookings.count_documents({"eventId": e["id"], "bookingStatus": {"$ne": "cancelled"}})
        e["waitlistCount"] = await db.waitlist.count_documents({"eventId": e["id"]})
    return events

@api.post("/admin/events")
async def admin_create_event(data: EventCreate, _=Depends(verify_admin)):
    event = {
        "id": str(uuid.uuid4()),
        **data.model_dump(),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.events.insert_one(event)
    return {k: v for k, v in event.items() if k != "_id"}

@api.put("/admin/events/{event_id}")
async def admin_update_event(event_id: str, data: EventUpdate, _=Depends(verify_admin)):
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    update_data["updatedAt"] = datetime.now(timezone.utc).isoformat()
    result = await db.events.update_one({"id": event_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Event not found")
    return await db.events.find_one({"id": event_id}, {"_id": 0})

@api.delete("/admin/events/{event_id}")
async def admin_delete_event(event_id: str, _=Depends(verify_admin)):
    result = await db.events.delete_one({"id": event_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"message": "Event deleted"}

@api.put("/admin/events/{event_id}/hero")
async def admin_set_hero_event(event_id: str, _=Depends(verify_admin)):
    await db.events.update_many({}, {"$set": {"heroCardVisible": False}})
    await db.events.update_one({"id": event_id}, {"$set": {"heroCardVisible": True}})
    return {"message": "Hero event updated"}

# ─── Admin Bookings ───────────────────────────────────────────────────
@api.get("/admin/bookings")
async def admin_list_bookings(event_id: Optional[str] = None, _=Depends(verify_admin)):
    query = {}
    if event_id:
        query["eventId"] = event_id
    return await db.bookings.find(query, {"_id": 0}).sort("createdAt", -1).to_list(1000)

@api.put("/admin/bookings/{booking_id}/status")
async def admin_update_booking_status(booking_id: str, data: StatusUpdate, _=Depends(verify_admin)):
    result = await db.bookings.update_one({"id": booking_id}, {"$set": {"bookingStatus": data.status, "updatedAt": datetime.now(timezone.utc).isoformat()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Booking not found")
    return {"message": f"Booking status updated to {data.status}"}

@api.put("/admin/bookings/{booking_id}/payment-status")
async def admin_update_payment_status(booking_id: str, data: StatusUpdate, _=Depends(verify_admin)):
    await db.bookings.update_one({"id": booking_id}, {"$set": {"paymentStatus": data.status, "updatedAt": datetime.now(timezone.utc).isoformat()}})
    return {"message": f"Payment status updated to {data.status}"}

@api.post("/admin/bookings/{booking_id}/resend-whatsapp")
async def admin_resend_booking_whatsapp(booking_id: str, _=Depends(verify_admin)):
    booking = await db.bookings.find_one({"id": booking_id}, {"_id": 0})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    result = send_registration_confirmation(
        booking.get("whatsappNumber") or booking["phoneNumber"],
        booking.get("firstName", ""), booking.get("eventName", ""),
        booking.get("eventDate", ""), booking.get("eventTime", ""),
        booking.get("venueArea", ""), booking.get("bookingStatus", "Reserved").capitalize()
    )
    await log_whatsapp("booking", booking_id, booking.get("whatsappNumber", ""),
                       "registration_confirmation", os.environ.get('TWILIO_CONTENT_SID_REG_CONFIRM', ''), {}, result)
    return {"success": result.get("success"), "error": result.get("error")}

@api.get("/admin/bookings/export")
async def admin_export_bookings(event_id: Optional[str] = None, _=Depends(verify_admin)):
    query = {"eventId": event_id} if event_id else {}
    bookings = await db.bookings.find(query, {"_id": 0}).to_list(5000)
    output = io.StringIO()
    if bookings:
        writer = csv.DictWriter(output, fieldnames=[k for k in bookings[0].keys() if k != "_id"])
        writer.writeheader()
        writer.writerows(bookings)
    return Response(content=output.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=bookings.csv"})

# ─── Admin Waitlist ───────────────────────────────────────────────────
@api.get("/admin/waitlist")
async def admin_list_waitlist(event_id: Optional[str] = None, _=Depends(verify_admin)):
    query = {}
    if event_id:
        query["eventId"] = event_id
    return await db.waitlist.find(query, {"_id": 0}).sort("createdAt", -1).to_list(1000)

@api.put("/admin/waitlist/{entry_id}/status")
async def admin_update_waitlist_status(entry_id: str, data: StatusUpdate, _=Depends(verify_admin)):
    result = await db.waitlist.update_one({"id": entry_id}, {"$set": {"waitlistStatus": data.status, "updatedAt": datetime.now(timezone.utc).isoformat()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    return {"message": f"Waitlist status updated to {data.status}"}

@api.post("/admin/waitlist/{entry_id}/resend-whatsapp")
async def admin_resend_waitlist_whatsapp(entry_id: str, _=Depends(verify_admin)):
    entry = await db.waitlist.find_one({"id": entry_id}, {"_id": 0})
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    result = send_registration_confirmation(
        entry.get("whatsappNumber") or entry["phoneNumber"],
        entry.get("firstName", ""), entry.get("eventName", "Cita Rush Event"),
        entry.get("eventDate", "TBA"), entry.get("eventTime", "TBA"),
        entry.get("venueArea", "Pune"), entry.get("waitlistStatus", "Waitlisted").capitalize()
    )
    await log_whatsapp("waitlist", entry_id, entry.get("whatsappNumber", ""),
                       "registration_confirmation", os.environ.get('TWILIO_CONTENT_SID_REG_CONFIRM', ''), {}, result)
    return {"success": result.get("success"), "error": result.get("error")}

@api.get("/admin/waitlist/export")
async def admin_export_waitlist(event_id: Optional[str] = None, _=Depends(verify_admin)):
    query = {"eventId": event_id} if event_id else {}
    entries = await db.waitlist.find(query, {"_id": 0}).to_list(5000)
    output = io.StringIO()
    if entries:
        writer = csv.DictWriter(output, fieldnames=[k for k in entries[0].keys() if k != "_id"])
        writer.writeheader()
        writer.writerows(entries)
    return Response(content=output.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=waitlist.csv"})

# ─── Admin WhatsApp Logs ──────────────────────────────────────────────
@api.get("/admin/whatsapp-logs")
async def admin_whatsapp_logs(_=Depends(verify_admin)):
    return await db.whatsapp_logs.find({}, {"_id": 0}).sort("createdAt", -1).to_list(500)

# ─── Admin Bulk Send ──────────────────────────────────────────────────
@api.post("/admin/bulk-send/event-reminder/{event_id}")
async def admin_bulk_event_reminder(event_id: str, _=Depends(verify_admin)):
    event = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    bookings = await db.bookings.find({"eventId": event_id, "bookingStatus": {"$in": ["confirmed", "reserved"]}, "whatsappOptIn": True}, {"_id": 0}).to_list(500)
    sent, failed = 0, 0
    for b in bookings:
        r = send_event_reminder(
            b.get("whatsappNumber") or b["phoneNumber"], b.get("firstName", ""),
            event.get("title", ""), event.get("eventDate", ""), event.get("eventTime", ""),
            event.get("venueArea", ""), event.get("dressCode", "Smart casual")
        )
        await log_whatsapp("booking", b["id"], b.get("whatsappNumber", ""), "event_reminder",
                           os.environ.get('TWILIO_CONTENT_SID_EVENT_REMINDER', ''), {}, r)
        if r.get("success"):
            sent += 1
        else:
            failed += 1
    # Also send to confirmed waitlist
    waitlist = await db.waitlist.find({"eventId": event_id, "waitlistStatus": "confirmed", "whatsappOptIn": True}, {"_id": 0}).to_list(500)
    for w in waitlist:
        r = send_event_reminder(
            w.get("whatsappNumber") or w["phoneNumber"], w.get("firstName", ""),
            event.get("title", ""), event.get("eventDate", ""), event.get("eventTime", ""),
            event.get("venueArea", ""), event.get("dressCode", "Smart casual")
        )
        await log_whatsapp("waitlist", w["id"], w.get("whatsappNumber", ""), "event_reminder",
                           os.environ.get('TWILIO_CONTENT_SID_EVENT_REMINDER', ''), {}, r)
        if r.get("success"):
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed, "total": sent + failed}

@api.post("/admin/bulk-send/checkin-details/{event_id}")
async def admin_bulk_checkin_details(event_id: str, _=Depends(verify_admin)):
    event = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    bookings = await db.bookings.find({"eventId": event_id, "bookingStatus": {"$in": ["confirmed", "reserved"]}, "whatsappOptIn": True}, {"_id": 0}).to_list(500)
    sent, failed = 0, 0
    for b in bookings:
        r = send_checkin_details(
            b.get("whatsappNumber") or b["phoneNumber"], b.get("firstName", ""),
            event.get("title", ""), event.get("venueName", ""),
            event.get("fullAddress") or event.get("venueArea", ""),
            event.get("reportingTime") or event.get("eventTime", ""),
            b.get("bookingStatus", "Confirmed").capitalize()
        )
        await log_whatsapp("booking", b["id"], b.get("whatsappNumber", ""), "checkin_details",
                           os.environ.get('TWILIO_CONTENT_SID_CHECKIN_DETAILS', ''), {}, r)
        if r.get("success"):
            sent += 1
        else:
            failed += 1
    waitlist = await db.waitlist.find({"eventId": event_id, "waitlistStatus": "confirmed", "whatsappOptIn": True}, {"_id": 0}).to_list(500)
    for w in waitlist:
        r = send_checkin_details(
            w.get("whatsappNumber") or w["phoneNumber"], w.get("firstName", ""),
            event.get("title", ""), event.get("venueName", ""),
            event.get("fullAddress") or event.get("venueArea", ""),
            event.get("reportingTime") or event.get("eventTime", ""),
            w.get("waitlistStatus", "Confirmed").capitalize()
        )
        await log_whatsapp("waitlist", w["id"], w.get("whatsappNumber", ""), "checkin_details",
                           os.environ.get('TWILIO_CONTENT_SID_CHECKIN_DETAILS', ''), {}, r)
        if r.get("success"):
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed, "total": sent + failed}

@api.post("/admin/test-whatsapp")
async def admin_test_whatsapp(data: ManualWhatsApp, _=Depends(verify_admin)):
    content_sid_map = {
        "registration_confirmation": os.environ.get('TWILIO_CONTENT_SID_REG_CONFIRM', ''),
        "event_reminder": os.environ.get('TWILIO_CONTENT_SID_EVENT_REMINDER', ''),
        "checkin_details": os.environ.get('TWILIO_CONTENT_SID_CHECKIN_DETAILS', ''),
    }
    content_sid = content_sid_map.get(data.templateType, '')
    result = send_whatsapp_template(data.recipientNumber, content_sid, data.variables or {})
    await log_whatsapp("admin_test", "", data.recipientNumber, data.templateType, content_sid, data.variables or {}, result)
    return result

# ─── Stats (backward compat) ─────────────────────────────────────────
@api.get("/stats")
async def get_stats():
    return {
        "events": await db.events.count_documents({}),
        "bookings": await db.bookings.count_documents({}),
        "waitlist": await db.waitlist.count_documents({}),
        "partner_inquiries": await db.partner_inquiries.count_documents({}),
    }

# ─── Seed ─────────────────────────────────────────────────────────────
@api.post("/seed")
async def seed_events():
    count = await db.events.count_documents({})
    if count > 0:
        return {"message": f"Already have {count} events, skipping seed"}
    sample = [
        {"id": str(uuid.uuid4()), "title": "Founders & Creators Night", "venueName": "The Daily All Day", "venueArea": "Koregaon Park", "fullAddress": "Lane 6, Koregaon Park, Pune", "city": "Pune", "eventDate": "2026-05-18", "eventTime": "7:30 PM", "reportingTime": "7:00 PM", "ageBand": "25-34", "miniDatesPerGuest": 6, "avgMatches": 3, "dressCode": "Smart casual", "totalMaleSpots": 12, "totalFemaleSpots": 12, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Hosted speed-dating", "Mini-dates + games", "Coordinated tables"], "heroCardVisible": True, "theme": "Founders & Creators", "description": "An intimate evening for entrepreneurs, artists, and builders.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "title": "Tech & Finance Mixer", "venueName": "Cafe Nirvana", "venueArea": "Viman Nagar", "fullAddress": "Viman Nagar, Pune", "city": "Pune", "eventDate": "2026-05-25", "eventTime": "8:00 PM", "reportingTime": "7:30 PM", "ageBand": "23-32", "miniDatesPerGuest": 7, "avgMatches": 3, "dressCode": "Smart casual", "totalMaleSpots": 14, "totalFemaleSpots": 14, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Hosted speed-dating", "Mini-dates + games"], "heroCardVisible": False, "theme": "Tech & Finance", "description": "Where analytical minds meet over curated conversations.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "title": "OTT & Music Lovers", "venueName": "Elephant & Co.", "venueArea": "Baner", "fullAddress": "Baner, Pune", "city": "Pune", "eventDate": "2026-06-01", "eventTime": "7:00 PM", "reportingTime": "6:30 PM", "ageBand": "22-30", "miniDatesPerGuest": 5, "avgMatches": 2, "dressCode": "Casual chic", "totalMaleSpots": 10, "totalFemaleSpots": 10, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Mini-dates + games", "Coordinated tables"], "heroCardVisible": False, "theme": "OTT & Music", "description": "Bond over shared taste in shows, films, and playlists.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "title": "Creative Professionals Evening", "venueName": "Pagdandi Books Chai Cafe", "venueArea": "Kalyani Nagar", "fullAddress": "Kalyani Nagar, Pune", "city": "Pune", "eventDate": "2026-06-08", "eventTime": "7:30 PM", "reportingTime": "7:00 PM", "ageBand": "26-35", "miniDatesPerGuest": 6, "avgMatches": 3, "dressCode": "Smart casual", "totalMaleSpots": 10, "totalFemaleSpots": 10, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Hosted speed-dating", "Mini-dates + games", "Coordinated tables"], "heroCardVisible": False, "theme": "Design & Media", "description": "For those who think in pixels, words, and frames.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "title": "Wellness & Travel Enthusiasts", "venueName": "Baner Social", "venueArea": "Aundh", "fullAddress": "Aundh, Pune", "city": "Pune", "eventDate": "2026-06-14", "eventTime": "6:30 PM", "reportingTime": "6:00 PM", "ageBand": "24-33", "miniDatesPerGuest": 6, "avgMatches": 2, "dressCode": "Casual chic", "totalMaleSpots": 12, "totalFemaleSpots": 12, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Mini-dates + games", "Hosted speed-dating"], "heroCardVisible": False, "theme": "Wellness & Travel", "description": "Meet someone who shares your love for adventure and mindful living.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
        {"id": str(uuid.uuid4()), "title": "After-Work Social", "venueName": "The Irish Village", "venueArea": "Koregaon Park", "fullAddress": "Koregaon Park, Pune", "city": "Pune", "eventDate": "2026-06-22", "eventTime": "8:00 PM", "reportingTime": "7:30 PM", "ageBand": "25-35", "miniDatesPerGuest": 5, "avgMatches": 2, "dressCode": "Business casual", "totalMaleSpots": 12, "totalFemaleSpots": 12, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Hosted speed-dating", "Coordinated tables"], "heroCardVisible": False, "theme": "Corporate Professionals", "description": "Unwind after work with curated conversations and new connections.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
    ]
    await db.events.insert_many(sample)
    return {"message": f"Seeded {len(sample)} events"}

# ═══════════════════════ APP SETUP ═══════════════════════════════════
app.include_router(api)

app.add_middleware(
    CORSMiddleware, allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"], allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

@app.on_event("startup")
async def startup_event():
    count = await db.events.count_documents({})
    if count == 0:
        logger.info("No events found, seeding database...")
        sample = [
            {"id": str(uuid.uuid4()), "title": "Founders & Creators Night", "venueName": "The Daily All Day", "venueArea": "Koregaon Park", "fullAddress": "Lane 6, Koregaon Park, Pune", "city": "Pune", "eventDate": "2026-05-18", "eventTime": "7:30 PM", "reportingTime": "7:00 PM", "ageBand": "25-34", "miniDatesPerGuest": 6, "avgMatches": 3, "dressCode": "Smart casual", "totalMaleSpots": 12, "totalFemaleSpots": 12, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Hosted speed-dating", "Mini-dates + games", "Coordinated tables"], "heroCardVisible": True, "theme": "Founders & Creators", "description": "An intimate evening for entrepreneurs, artists, and builders.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
            {"id": str(uuid.uuid4()), "title": "Tech & Finance Mixer", "venueName": "Cafe Nirvana", "venueArea": "Viman Nagar", "fullAddress": "Viman Nagar, Pune", "city": "Pune", "eventDate": "2026-05-25", "eventTime": "8:00 PM", "reportingTime": "7:30 PM", "ageBand": "23-32", "miniDatesPerGuest": 7, "avgMatches": 3, "dressCode": "Smart casual", "totalMaleSpots": 14, "totalFemaleSpots": 14, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Hosted speed-dating", "Mini-dates + games"], "heroCardVisible": False, "theme": "Tech & Finance", "description": "Where analytical minds meet over curated conversations.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
            {"id": str(uuid.uuid4()), "title": "OTT & Music Lovers", "venueName": "Elephant & Co.", "venueArea": "Baner", "fullAddress": "Baner, Pune", "city": "Pune", "eventDate": "2026-06-01", "eventTime": "7:00 PM", "reportingTime": "6:30 PM", "ageBand": "22-30", "miniDatesPerGuest": 5, "avgMatches": 2, "dressCode": "Casual chic", "totalMaleSpots": 10, "totalFemaleSpots": 10, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Mini-dates + games", "Coordinated tables"], "heroCardVisible": False, "theme": "OTT & Music", "description": "Bond over shared taste in shows, films, and playlists.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
            {"id": str(uuid.uuid4()), "title": "Creative Professionals Evening", "venueName": "Pagdandi Books Chai Cafe", "venueArea": "Kalyani Nagar", "fullAddress": "Kalyani Nagar, Pune", "city": "Pune", "eventDate": "2026-06-08", "eventTime": "7:30 PM", "reportingTime": "7:00 PM", "ageBand": "26-35", "miniDatesPerGuest": 6, "avgMatches": 3, "dressCode": "Smart casual", "totalMaleSpots": 10, "totalFemaleSpots": 10, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Hosted speed-dating", "Mini-dates + games", "Coordinated tables"], "heroCardVisible": False, "theme": "Design & Media", "description": "For those who think in pixels, words, and frames.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
            {"id": str(uuid.uuid4()), "title": "Wellness & Travel Enthusiasts", "venueName": "Baner Social", "venueArea": "Aundh", "fullAddress": "Aundh, Pune", "city": "Pune", "eventDate": "2026-06-14", "eventTime": "6:30 PM", "reportingTime": "6:00 PM", "ageBand": "24-33", "miniDatesPerGuest": 6, "avgMatches": 2, "dressCode": "Casual chic", "totalMaleSpots": 12, "totalFemaleSpots": 12, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Mini-dates + games", "Hosted speed-dating"], "heroCardVisible": False, "theme": "Wellness & Travel", "description": "Meet someone who shares your love for adventure and mindful living.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
            {"id": str(uuid.uuid4()), "title": "After-Work Social", "venueName": "The Irish Village", "venueArea": "Koregaon Park", "fullAddress": "Koregaon Park, Pune", "city": "Pune", "eventDate": "2026-06-22", "eventTime": "8:00 PM", "reportingTime": "7:30 PM", "ageBand": "25-35", "miniDatesPerGuest": 5, "avgMatches": 2, "dressCode": "Business casual", "totalMaleSpots": 12, "totalFemaleSpots": 12, "eventType": "speed-dating", "eventStatus": "published", "tags": ["Hosted speed-dating", "Coordinated tables"], "heroCardVisible": False, "theme": "Corporate Professionals", "description": "Unwind after work with curated conversations and new connections.", "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()},
        ]
        await db.events.insert_many(sample)
        logger.info(f"Seeded {len(sample)} events")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
