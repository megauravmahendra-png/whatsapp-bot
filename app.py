import sys
import os
sys.stdout.reconfigure(line_buffering=True)

from flask import Flask, request, jsonify
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json

app = Flask(__name__)

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1008870035641514")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "my_secret_verify_token")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")

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


def save_to_sheets(phone, action_number, action_label, raw_message):
    try:
        print("=== SHEETS DEBUG START ===", flush=True)

        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if not creds_json:
            print("ERROR: GOOGLE_CREDENTIALS_JSON is missing!", flush=True)
            return False
        print("✓ Credentials JSON found", flush=True)

        spreadsheet_id = os.environ.get("SPREADSHEET_ID")
        if not spreadsheet_id:
            print("ERROR: SPREADSHEET_ID is missing!", flush=True)
            return False
        print(f"✓ Spreadsheet ID: {spreadsheet_id}", flush=True)

        creds_dict = json.loads(creds_json)
        print(f"✓ Parsed credentials for: {creds_dict.get('client_email')}", flush=True)

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        print("✓ Credentials object created", flush=True)

        client = gspread.authorize(creds)
        print("✓ Gspread client authorized", flush=True)

        spreadsheet = client.open_by_key(spreadsheet_id)
        print("✓ Spreadsheet opened", flush=True)

        sheet = spreadsheet.sheet1
        existing = sheet.get_all_values()
        if not existing:
            sheet.append_row(["Timestamp", "Phone Number", "Action #", "Action Label", "Raw Message"])
            print("✓ Headers added", flush=True)

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            phone,
            action_number,
            action_label,
            raw_message
        ]
        sheet.append_row(row)
        print(f"✓ Row saved: {row}", flush=True)
        print("=== SHEETS DEBUG END ===", flush=True)
        return True

    except json.JSONDecodeError as e:
        print(f"ERROR: JSON parse failed - {e}", flush=True)
    except gspread.exceptions.APIError as e:
        print(f"ERROR: Sheets API error - {e}", flush=True)
        print("HINT: Enable Google Sheets API + Google Drive API in Google Cloud Console", flush=True)
    except gspread.exceptions.SpreadsheetNotFound:
        print("ERROR: Spreadsheet not found - check SPREADSHEET_ID and sharing", flush=True)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", flush=True)

    return False


def send_whatsapp_message(to, message):
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
    print(f"WhatsApp send: {response.status_code} - {response.text}", flush=True)
    return response.status_code == 200


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✓ Webhook verified", flush=True)
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def handle_message():
    data = request.get_json()
    print(f"RAW INCOMING: {json.dumps(data)}", flush=True)

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "statuses" in value and "messages" not in value:
            print("Skipping status update", flush=True)
            return jsonify({"status": "ok"}), 200

        messages = value.get("messages", [])
        if not messages:
            print("No messages in payload", flush=True)
            return jsonify({"status": "ok"}), 200

        message = messages[0]
        sender_phone = message["from"]
        msg_type = message.get("type", "")
        print(f"Message type: {msg_type} from {sender_phone}", flush=True)

        if msg_type != "text":
            send_whatsapp_message(sender_phone, "Please send a text message 😊")
            return jsonify({"status": "ok"}), 200

        incoming_text = message["text"]["body"].strip()
        print(f"Text received: '{incoming_text}'", flush=True)

        if incoming_text in ACTION_LABELS:
            action_label = ACTION_LABELS[incoming_text]
            print(f"Valid action: {incoming_text} = {action_label}", flush=True)
            save_to_sheets(sender_phone, incoming_text, action_label, incoming_text)
            send_whatsapp_message(sender_phone, f"✅ Got it! You selected: *{action_label}*\n\nWe'll get back to you shortly!")
        else:
            print("Sending action menu", flush=True)
            send_whatsapp_message(sender_phone, ACTION_MENU)

    except Exception as e:
        print(f"EXCEPTION: {type(e).__name__}: {e}", flush=True)

    return jsonify({"status": "ok"}), 200


@app.route("/test-sheets", methods=["GET"])
def test_sheets():
    """Test endpoint to verify Google Sheets connection without WhatsApp."""
    print("=== TEST SHEETS ENDPOINT CALLED ===", flush=True)
    result = save_to_sheets("911234567890", "1", "Schedule a meeting", "direct test")
    return f"Sheets save result: {result}", 200


@app.route("/", methods=["GET"])
def home():
    return "WhatsApp Bot is running! 🤖", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
