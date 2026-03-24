import logging
import os
from flask import Flask, Response, request
from check_slots import get_session_and_csrf, get_availability, find_open_slots, format_time, parse_time_input
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route("/slots")
def slots():
    after_raw = request.args.get("after", "8pm")
    try:
        after_time = parse_time_input(after_raw)
    except ValueError as e:
        return Response(str(e), status=400, mimetype="text/plain")

    try:
        session, csrf = get_session_and_csrf()
    except Exception as e:
        logger.error("Failed to initialize session with external API: %s", e)
        return Response(
            f"Service unavailable: could not reach the reservations API ({e})",
            status=503,
            mimetype="text/plain",
        )

    lines = []

    for i in range(6):
        d = date.today() + timedelta(days=i)
        label = d.strftime("%A, %b %-d")
        if i == 0:
            label += " (Today)"
        elif i == 1:
            label += " (Tomorrow)"

        try:
            avail = get_availability(session, csrf, d)
            open_slots = find_open_slots(avail, after_time)
        except Exception as e:
            logger.error("Failed to fetch availability for %s: %s", d.isoformat(), e)
            lines.append(label)
            lines.append(f"  Error fetching availability: {e}")
            lines.append("")
            continue

        lines.append(label)
        if not open_slots:
            lines.append(f"  No open slots after {format_time(after_time)}")
        else:
            by_court = {}
            for s in open_slots:
                by_court.setdefault(s["court"], []).append(s["time"])
            for court, times in by_court.items():
                lines.append(f"  {court}")
                lines.append(f"    {'  '.join(format_time(t) for t in times)}")
        lines.append("")

    return Response("\n".join(lines), mimetype="text/plain")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
