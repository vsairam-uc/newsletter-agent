import os
from datetime import datetime

import resend

# Setup local archives directory for email backups
ARCHIVES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archives")


def send_newsletter_email(
    subject: str, html_content: str, recipient: list[str] | str | None = None
) -> bool:
    """Send the HTML newsletter via Resend API, with local archive backup."""
    # Ensure archives directory exists
    os.makedirs(ARCHIVES_DIR, exist_ok=True)

    # 1. Save to local HTML backup file
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_subject = "".join(
        c for c in subject if c.isalnum() or c in (" ", "-", "_")
    ).replace(" ", "_")
    backup_filename = f"{timestamp}_{safe_subject}.html"
    backup_filepath = os.path.join(ARCHIVES_DIR, backup_filename)

    try:
        with open(backup_filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"Saved local email backup to: {backup_filepath}")
    except Exception as e:
        print(f"Error saving local email backup: {e}")

    # 2. Check for Resend API Key
    api_key = os.environ.get("RESEND_API_KEY")

    # Check if the API key is not set or is still the default placeholder
    if not api_key or "placeholder" in api_key.lower():
        print(
            "Warning: RESEND_API_KEY is not configured or is a placeholder. Skipping email dispatch (local backup saved)."
        )
        return False

    resend.api_key = api_key

    # Set default recipient if not provided
    if not recipient:
        recipient = os.environ.get("SUBSCRIBER_EMAIL", "delivered@resend.dev")

    # Ensure recipient is a list
    recipients = recipient if isinstance(recipient, list) else [recipient]

    any_success = False
    for r in recipients:
        email_addr = str(r).strip()
        if not email_addr:
            continue
        try:
            params = {
                "from": "Systems & AI Digest <onboarding@resend.dev>",
                "to": [email_addr],
                "subject": subject,
                "html": html_content,
            }

            print(f"Attempting to send email via Resend to {email_addr}...")
            email = resend.Emails.send(params)
            print(
                f"Email sent successfully to {email_addr}. Resend ID: {email.get('id')}"
            )
            any_success = True
        except Exception as e:
            print(f"Error sending email to {email_addr} via Resend API: {e}")

    return any_success
