from django.core.management.base import BaseCommand
from django.conf import settings
from main.emailer import send_gmail_message, get_gmail_credentials


class Command(BaseCommand):
    help = "Tests Google Gmail API email sending with configured OAuth2 credentials."

    def add_arguments(self, parser):
        parser.add_argument(
            "recipient",
            type=str,
            help="Recipient email address to send the test confirmation to.",
        )

    def handle(self, *args, **options):
        recipient = options["recipient"]
        self.stdout.write(self.style.NOTICE(f"Checking Gmail API configuration..."))

        client_id = getattr(settings, "GMAIL_CLIENT_ID", "")
        client_secret = getattr(settings, "GMAIL_CLIENT_SECRET", "")
        refresh_token = getattr(settings, "GMAIL_REFRESH_TOKEN", "")
        sender_email = getattr(settings, "GMAIL_SENDER_EMAIL", "")

        self.stdout.write(f"  - GMAIL_CLIENT_ID: {'Configured' if client_id else 'MISSING'}")
        self.stdout.write(f"  - GMAIL_CLIENT_SECRET: {'Configured' if client_secret else 'MISSING'}")
        self.stdout.write(f"  - GMAIL_REFRESH_TOKEN: {'Configured' if refresh_token else 'MISSING'}")
        self.stdout.write(f"  - GMAIL_SENDER_EMAIL: {sender_email or 'Default'}")

        if not (client_id and client_secret and refresh_token):
            self.stdout.write(
                self.style.WARNING(
                    "\n[Notice] Gmail API credentials are not yet configured in settings/.env.\n"
                    "Add GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN to your .env file."
                )
            )
            return

        self.stdout.write(self.style.NOTICE(f"\nAttempting token refresh and sending test email to: {recipient}..."))

        subject = "DBRecruitAI - Gmail API Test Message"
        html_content = (
            "<div style='font-family: sans-serif; padding: 20px;'>"
            "<h2 style='color: #2563eb;'>Gmail API Connection Successful!</h2>"
            "<p>Your DBRecruitAI application is properly authenticated with Google Gmail API.</p>"
            "<p>Applicants will now receive their submission confirmations directly from your configured email address.</p>"
            "</div>"
        )
        text_content = (
            "Gmail API Connection Successful!\n\n"
            "Your DBRecruitAI application is properly authenticated with Google Gmail API."
        )

        result = send_gmail_message(
            to_email=recipient,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
        )

        if result.get("success"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n[Success] Test email dispatched successfully! Message ID: {result.get('message_id')}"
                )
            )
        else:
            err_text = str(result.get("error", ""))
            self.stdout.write(
                self.style.ERROR(
                    f"\n[Error] Failed to send email: {err_text}"
                )
            )
            if "invalid_grant" in err_text:
                self.stdout.write(
                    self.style.WARNING(
                        "\n--- DIAGNOSIS: invalid_grant detected ---"
                        "\nCause: In Google Cloud Console, publishing the app (or switching between 'Testing'"
                        "\nand 'In production') automatically invalidates all existing OAuth 2.0 refresh tokens."
                        "\n"
                        "\nResolution Steps:"
                        "\n1. Open Google OAuth 2.0 Playground: https://developers.google.com/oauthplayground"
                        "\n2. Click the Gear icon (top right) -> Check 'Use your own OAuth credentials'"
                        "\n3. Enter your GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET"
                        "\n4. In Step 1, input scope: https://www.googleapis.com/auth/gmail.send and click 'Authorize APIs'"
                        "\n5. Sign in with your sending Gmail account and grant permissions"
                        "\n6. In Step 2, click 'Exchange authorization code for tokens'"
                        "\n7. Copy the new 'Refresh token' and update GMAIL_REFRESH_TOKEN in your .env file"
                        "\n------------------------------------------"
                    )
                )
