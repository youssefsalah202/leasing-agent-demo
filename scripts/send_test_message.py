"""CLI to POST a fake inbound SMS to the locally running webhook, so you can
poke at the agent without a real Quo account.

Usage:
    python scripts/send_test_message.py --body "Do you allow pets?"
    python scripts/send_test_message.py --phone +15559998888 --body "I'd like to book a tour"
"""

from __future__ import annotations

import argparse

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", default="+15551234567", help="Sender phone number")
    parser.add_argument("--body", required=True, help="SMS text to send")
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks/quo/sms")
    args = parser.parse_args()

    response = httpx.post(args.url, json={"from": args.phone, "body": args.body}, timeout=60)
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
