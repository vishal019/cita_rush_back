import os
import smtplib
from dotenv import load_dotenv
from pathlib import Path

# Load env from backend/.env
backend_env = Path(r"v:\digital diaries\Clinet_work\Cita_rush\cita_rush\backend\.env")
load_dotenv(backend_env)

sender_email = os.environ.get('GMAIL_USER')
sender_password = os.environ.get('GMAIL_APP_PASSWORD')

print(f"Testing with Email: {sender_email}")
# We won't print the password for security, just check if it exists
if not sender_password:
    print("Error: GMAIL_APP_PASSWORD not set")
    exit(1)

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender_email, sender_password)
        print("Success: Logged in to Gmail SMTP!")
except Exception as e:
    print(f"Failure: {e}")
