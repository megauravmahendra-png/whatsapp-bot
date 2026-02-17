from flask import Flask, request, jsonify
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import os
import json

app = Flask(__name__)

# ============================================================
# CONFIGURATION — Fill these in with your actual values
# ============================================================
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "YOUR_ACCESS_TOKEN_HERE")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1008870035641514")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "my_secret_verify_token")  # You can set this to anything
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_GOOGLE_SHEET_ID_HERE")
# ============================================================

# Action items menu that gets sent to users
ACTION_MENU = """👋 Hi! Thanks for reaching out.

Please choose an action by replying with a number:

1️⃣ Schedule a meeting
2️⃣ Get pricing info
3️⃣ Ask a question
4️⃣ Request a callback
5️⃣ Something else

Just reply with the number (1-5)."""

ACTION_LABELS = {
    "1": "Schedule a meeting",
    "2": "Get pricing info",
    "3": "Ask a question",
    "4": "Request a callback",
    "5": "Something else"
}

# Track who has already received the menu (in-memory, resets on restart)
# For production, use a database instead
sent_menu_to = set()


# ============================================================
# GOOGLE SHEETS SETUP
# ============================================================
def get_sheets_client():
    """Connect to Google Sheets using service account credentials."""
    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if not creds_json:
            print("WARNING: GOOGLE_CREDENTIALS_JSON not set")
            return None
        
        creds_dict = json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        print(f"Google Sheets error: {e}")
        return None


def save_to_sheets(phone, action_number, action_label, raw_message):
    """Save a user's response to Google Sheets."""
    try:
        client = get_sheets_client()
        if not client:
            print("Could not connect to Google Sheets")
            return False
        
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        
        # Add header row if sheet is empty
        if sheet.row_count == 0 or sheet.cell(1, 1).value != "Timestamp":
            sheet.insert_row(["Timestamp", "Phone Number", "Action #", "Action Label", "Raw Message"], 1)
        
        # Append the new row
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            phone,
            action_number,
            action_label,
            raw_message
        ]
        sheet.append_row(row)
        print(f"Saved to sheets: {row}")
        return True
    except Exception as e:
        print(f"Error saving to sheets: {e}")
        return False


# ============================================================
# WHATSAPP MESSAGING
# ============================================================
def send_whatsapp_message(to, message):
    """Send a text message via WhatsApp Cloud API."""
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(url, headers=headers, json=payload)
    print(f"Send message response: {response.status_code} - {response.text}")
    return response.status_code == 200


# ============================================================
# WEBHOOK ROUTES
# ============================================================
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Meta calls this to verify your webhook URL."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified successfully!")
        return challenge, 200
    else:
        print(f"Webhook verification failed. Token received: {token}")
        return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def handle_message():
    """Receives incoming WhatsApp messages."""
    data = request.get_json()
    print(f"Incoming webhook data: {json.dumps(data, indent=2)}")

    try:
        # Navigate to the message
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        # Ignore status updates (delivered, read, etc.)
        if "statuses" in value:
            return jsonify({"status": "ok"}), 200

        messages = value.get("messages", [])
        if not messages:
            return jsonify({"status": "ok"}), 200

        message = messages[0]
        sender_phone = message["from"]
        msg_type = message.get("type", "")

        # Only handle text messages
        if msg_type != "text":
            send_whatsapp_message(sender_phone, "Please send a text message to interact with me. 😊")
            return jsonify({"status": "ok"}), 200

        incoming_text = message["text"]["body"].strip()
        print(f"Message from {sender_phone}: {incoming_text}")

        # If this is the first time we hear from them, send the menu
        if sender_phone not in sent_menu_to:
            sent_menu_to.add(sender_phone)
            send_whatsapp_message(sender_phone, ACTION_MENU)

        # If they replied with a number 1-5, log it
        elif incoming_text in ACTION_LABELS:
            action_label = ACTION_LABELS[incoming_text]
            
            # Save to Google Sheets
            save_to_sheets(sender_phone, incoming_text, action_label, incoming_text)
            
            # Confirm to user
            confirmation = f"✅ Got it! You selected: *{action_label}*\n\nWe'll get back to you shortly. Thank you!"
            send_whatsapp_message(sender_phone, confirmation)

        else:
            # They sent something unrecognized — resend the menu
            resend = "Please reply with a number between 1 and 5.\n\n" + ACTION_MENU
            send_whatsapp_message(sender_phone, resend)

    except Exception as e:
        print(f"Error processing message: {e}")

    return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def home():
    return "WhatsApp Bot is running! 🤖", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
