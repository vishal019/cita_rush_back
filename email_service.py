import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

def _send_email(recipient_email, subject, html_content):
    sender_email = os.environ.get('GMAIL_USER')
    sender_password = os.environ.get('GMAIL_APP_PASSWORD')

    if not sender_email or not sender_password:
        logger.warning("Gmail credentials not configured")
        return {"success": False, "error": "Gmail credentials not configured"}

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"Cita Rush <{sender_email}>"
    message["To"] = recipient_email
    message.attach(MIMEText(html_content, "html"))

    try:
        # Using Port 587 with STARTTLS for better compatibility
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, message.as_string())
        logger.info(f"Email sent to {recipient_email}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Email send failed to {recipient_email}: {e}")
        return {"success": False, "error": str(e)}

def send_booking_email(recipient_email: str, full_name: str, event_name: str, event_date: str, event_time: str, venue_area: str):
    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
          <h2 style="color: #e91e63;">Spot Successfully Booked!</h2>
          <p>Hi <strong>{full_name}</strong>,</p>
          <p>Great news! Your spot for <strong>{event_name}</strong> has been successfully confirmed.</p>
          
          <div style="background-color: #f9f9f9; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <h3 style="margin-top: 0;">Event Details:</h3>
            <p style="margin: 5px 0;"><strong>Date:</strong> {event_date}</p>
            <p style="margin: 5px 0;"><strong>Time:</strong> {event_time}</p>
            <p style="margin: 5px 0;"><strong>Location:</strong> {venue_area}</p>
          </div>
          
          <p>We're excited to see you there! If you have any questions, feel free to reply to this email.</p>
          <p>Best regards,<br>The Cita Rush Team</p>
          <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
          <p style="font-size: 0.8em; color: #777;">You are receiving this because you booked an event on Cita Rush.</p>
        </div>
      </body>
    </html>
    """
    return _send_email(recipient_email, f"Booking Confirmed: {event_name} - Cita Rush", html)

def send_waitlist_email(recipient_email: str, full_name: str, event_name: str, event_date: str, event_time: str, venue_area: str):
    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
          <h2 style="color: #2196f3;">Waitlist Confirmed!</h2>
          <p>Hi <strong>{full_name}</strong>,</p>
          <p>You've been added to the waitlist for <strong>{event_name}</strong>.</p>
          
          <div style="background-color: #f9f9f9; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <h3 style="margin-top: 0;">Event Details:</h3>
            <p style="margin: 5px 0;"><strong>Date:</strong> {event_date or "TBA"}</p>
            <p style="margin: 5px 0;"><strong>Time:</strong> {event_time or "TBA"}</p>
            <p style="margin: 5px 0;"><strong>Location:</strong> {venue_area or "Pune"}</p>
          </div>
          
          <p>If a spot becomes available, we'll notify you immediately via email or WhatsApp.</p>
          <p>Best regards,<br>The Cita Rush Team</p>
          <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
          <p style="font-size: 0.8em; color: #777;">You are receiving this because you joined the waitlist for an event on Cita Rush.</p>
        </div>
      </body>
    </html>
    """
    return _send_email(recipient_email, f"Waitlist Confirmed: {event_name} - Cita Rush", html)
