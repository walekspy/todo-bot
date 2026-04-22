"""
Run this script ONCE to authorize Google Tasks access.
It will open a browser window for Google sign-in and save the token.

Usage:
    python get_google_token.py

Requirements:
    - credentials/google_oauth.json  (OAuth Desktop app credentials from Google Cloud Console)

Output:
    - credentials/google_tasks_token.json  (token used by the bot)
"""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/tasks"]
CREDENTIALS_FILE = Path("credentials/google_oauth.json")
TOKEN_FILE = Path("credentials/google_tasks_token.json")

if not CREDENTIALS_FILE.exists():
    print(f"ERROR: {CREDENTIALS_FILE} not found.")
    print("Download it from Google Cloud Console:")
    print("  APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON")
    exit(1)

TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
creds = flow.run_local_server(port=0)

TOKEN_FILE.write_text(creds.to_json())
print(f"Token saved to {TOKEN_FILE}")
print("You can now start the bot.")
