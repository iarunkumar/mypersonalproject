#!/usr/bin/env python3
"""
Fremont Pickleball Court Availability Bot
Checks open slots after 8pm for the next 6 days (groupId=6 = Pickleball Courts)

Usage:
    python3 check_slots.py              # Check and print results
    python3 check_slots.py --watch 5    # Re-check every 5 minutes
"""

import requests
import json
import re
import time
import random
import argparse
from datetime import datetime, timedelta, date

BASE_URL = "https://anc.apm.activecommunities.com/fremont"
LANDING_URL = f"{BASE_URL}/reservation/landing/quick?groupId=6&locale=en-US"
AVAIL_URL   = f"{BASE_URL}/rest/reservation/quickreservation/availability?locale=en-US"

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
]

def _base_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Referer": LANDING_URL,
        "x-requested-with": "XMLHttpRequest",
        "page_info": '{"page_number":1,"total_records_per_page":20}',
    }

# Status codes from the API
# 0 = Available, 1 = Booked/Reserved
STATUS_LABELS = {0: "Available", 1: "Booked"}

AFTER_8PM = {"20:00:00", "20:30:00", "21:00:00", "21:30:00"}

# Re-initialize session every N days-worth of checks to avoid stale session fingerprint
SESSION_REFRESH_INTERVAL = 10


def get_session_and_csrf():
    """Load the landing page to establish a session and extract the CSRF token."""
    session = requests.Session()
    session.headers.update(_base_headers())

    resp = session.get(LANDING_URL, timeout=15)
    resp.raise_for_status()

    # Extract CSRF token from HTML (stored as window.__csrfToken = "...")
    m = re.search(r'__csrfToken\s*[=:]\s*["\']([a-f0-9\-]{36})["\']', resp.text)
    if not m:
        # Fallback: look for any UUID-like csrf pattern
        m = re.search(r'csrf[_\-]?[Tt]oken["\s]*[:=]["\s]*([a-f0-9\-]{36})', resp.text)
    if not m:
        raise RuntimeError("Could not find CSRF token in page HTML")

    csrf_token = m.group(1)
    return session, csrf_token


def get_availability(session, csrf_token, check_date: date):
    """POST to the availability endpoint for a given date. Returns parsed JSON body."""
    payload = {
        "facility_group_id": 6,
        "customer_id": 0,
        "company_id": 0,
        "reserve_date": check_date.strftime("%Y-%m-%d"),
        "start_time": None,
        "end_time": None,
        "resident": True,
        "reload": True,
        "change_time_range": False,
    }
    headers = {
        **_base_headers(),
        "content-type": "application/json;charset=utf-8",
        "x-csrf-token": csrf_token,
    }
    resp = session.post(AVAIL_URL, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("headers", {}).get("response_code") != "0000":
        msg = data.get("headers", {}).get("response_message", "Unknown error")
        raise RuntimeError(f"API error: {msg}")

    return data["body"]["availability"]


def find_open_slots(availability: dict, after_time: str = "20:00:00") -> list[dict]:
    """
    Return list of open slots >= after_time.
    Each entry: {"court": str, "time": str}
    """
    time_slots = availability["time_slots"]
    open_slots = []

    for resource in availability["resources"]:
        court_name = resource["resource_name"]
        slot_details = resource["time_slot_details"]

        for i, slot_time in enumerate(time_slots):
            if slot_time < after_time:
                continue
            if i >= len(slot_details):
                continue
            status = slot_details[i]["status"]
            if status == 0:  # Available
                open_slots.append({"court": court_name, "time": slot_time})

    return open_slots


def format_time(t: str) -> str:
    """Convert 20:00:00 -> 8:00 PM"""
    h, m, _ = t.split(":")
    h, m = int(h), int(m)
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def parse_time_input(t: str) -> str:
    """
    Parse human-friendly time input into HH:MM:SS format.
    Accepts: 8pm, 8PM, 20, 20:00, 20:00:00, 8:30pm, 8:30 PM
    """
    import re
    t = t.strip().lower().replace(" ", "")

    # Match patterns like 8pm, 8:30pm, 20, 20:00, 20:00:00
    m = re.match(r'^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?(am|pm)?$', t)
    if not m:
        raise ValueError(f"Unrecognized time format: '{t}'. Try: 8pm, 20, 20:30, 8:30pm")

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    second = int(m.group(3) or 0)
    meridiem = m.group(4)

    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time: {t}")

    return f"{hour:02d}:{minute:02d}:{second:02d}"


def check_and_print(days: int = 6, after_time: str = "20:00:00"):
    """Main check: print open slots after after_time for the next `days` days."""
    # Add 1 day to the input
    days = days + 1
    
    print(f"\n{'='*60}")
    print(f"  Fremont Pickleball - Open Slots After {format_time(after_time)}")
    print(f"  Checked: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    try:
        session, csrf_token = get_session_and_csrf()
    except Exception as e:
        print(f"  ERROR: Failed to initialize session: {e}")
        return False

    today = date.today()
    found_any = False

    for day_offset in range(days):
        # Refresh session periodically to avoid stale session fingerprint
        if day_offset > 0 and day_offset % SESSION_REFRESH_INTERVAL == 0:
            session, csrf_token = get_session_and_csrf()

        check_date = today + timedelta(days=day_offset)
        label = check_date.strftime("%A, %b %-d")
        if day_offset == 0:
            label += " (Today)"
        elif day_offset == 1:
            label += " (Tomorrow)"

        try:
            avail = get_availability(session, csrf_token, check_date)
            open_slots = find_open_slots(avail, after_time)
        except Exception as e:
            print(f"\n  {label}: ERROR - {e}")
            continue

        print(f"\n  {label}:")

        if not open_slots:
            print(f"    (no open slots after {format_time(after_time)})")
        else:
            found_any = True
            by_court: dict[str, list[str]] = {}
            for slot in open_slots:
                by_court.setdefault(slot["court"], []).append(slot["time"])

            for court, times in by_court.items():
                time_strs = "  ".join(format_time(t) for t in times)
                print(f"    ✓ {court}")
                print(f"      {time_strs}")

        # Random delay between requests to mimic human browsing
        if day_offset < days - 1:
            time.sleep(random.uniform(1.5, 4.0))

    print(f"\n{'='*60}\n")
    return found_any


def main():
    parser = argparse.ArgumentParser(description="Check Fremont pickleball court availability")
    parser.add_argument("--days", type=int, default=6, help="Number of days to check (default: 6)")
    parser.add_argument("--after", default="8pm", help="Show slots at or after this time. e.g. 8pm, 20, 20:30, 7:30pm (default: 8pm)")
    args = parser.parse_args()

    after_time = parse_time_input(args.after)
    check_and_print(days=args.days, after_time=after_time)


if __name__ == "__main__":
    main()
