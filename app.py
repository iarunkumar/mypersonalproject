import logging
import os
from flask import Flask, Response, request, render_template_string
from check_slots import get_session_and_csrf, get_availability, find_open_slots, format_time, parse_time_input
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# HTML template for the index page with dropdowns
INDEX_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Slot Availability Checker</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 600px; margin: 0 auto; }
        label { display: block; margin-top: 10px; font-weight: bold; }
        select { padding: 8px; font-size: 14px; margin-top: 5px; }
        button { margin-top: 20px; padding: 10px 20px; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        button:hover { background-color: #0056b3; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Slot Availability Checker</h1>
        <form method="GET" action="/slots">
            <label for="days">Days to Show:</label>
            <select id="days" name="days" required>
                <option value="">Select number of days</option>
                <option value="1">1 day</option>
                <option value="2">2 days</option>
                <option value="3">3 days</option>
                <option value="4">4 days</option>
                <option value="5">5 days</option>
                <option value="6">6 days</option>
                <option value="7">7 days</option>
            </select>

            <label for="time">Starting from Time:</label>
            <select id="time" name="time" required>
                <option value="">Select time</option>
                <option value="9am">9:00 AM</option>
                <option value="10am">10:00 AM</option>
                <option value="11am">11:00 AM</option>
                <option value="12pm">12:00 PM</option>
                <option value="1pm">1:00 PM</option>
                <option value="2pm">2:00 PM</option>
                <option value="3pm">3:00 PM</option>
                <option value="4pm">4:00 PM</option>
                <option value="5pm">5:00 PM</option>
                <option value="6pm">6:00 PM</option>
                <option value="7pm">7:00 PM</option>
                <option value="8pm">8:00 PM</option>
                <option value="9pm">9:00 PM</option>
            </select>

            <button type="submit">Check Availability</button>
        </form>
    </div>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(INDEX_TEMPLATE)

@app.route("/slots")
def slots():
    after_raw = request.args.get("time", "9am")
    days_raw = request.args.get("days", "6")
    
    # Validate days parameter
    try:
        days_count = int(days_raw)
        if days_count < 1 or days_count > 7:
            return Response("Days must be between 1 and 7", status=400, mimetype="text/html")
    except ValueError:
        return Response("Invalid days parameter", status=400, mimetype="text/html")
    
    try:
        after_time = parse_time_input(after_raw)
    except ValueError as e:
        return Response(f"<h2>Error: {str(e)}</h2>", status=400, mimetype="text/html")

    try:
        session, csrf = get_session_and_csrf()
    except Exception as e:
        logger.error("Failed to initialize session with external API: %s", e)
        return Response(
            f"<h2>Service unavailable: could not reach the reservations API ({e})</h2>",
            status=503,
            mimetype="text/html",
        )

    # Build HTML content
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Slot Availability</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
            .back-button {{ padding: 10px 20px; background-color: #6c757d; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; text-decoration: none; }}
            .back-button:hover {{ background-color: #5a6268; }}
            h1 {{ color: #333; }}
            .date-header {{ 
                background-color: #007bff; 
                color: white; 
                padding: 15px; 
                margin-top: 20px; 
                margin-bottom: 10px;
                border-radius: 4px;
                font-size: 18px;
                font-weight: bold;
            }}
            .court-name {{
                background-color: #e7f3ff;
                color: #0056b3;
                padding: 10px 15px;
                margin-top: 10px;
                margin-bottom: 8px;
                border-left: 4px solid #0056b3;
                font-weight: bold;
            }}
            .time-slots {{
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin-left: 15px;
                margin-bottom: 10px;
            }}
            .time-slot {{
                background-color: #28a745;
                color: white;
                padding: 10px 15px;
                border-radius: 4px;
                font-weight: bold;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .no-slots {{
                color: #666;
                font-style: italic;
                margin-left: 15px;
                margin-top: 10px;
                padding: 10px;
                background-color: #fff3cd;
                border-left: 4px solid #ffc107;
                border-radius: 4px;
            }}
            .error {{
                color: #dc3545;
                background-color: #f8d7da;
                padding: 10px 15px;
                margin-top: 10px;
                border-left: 4px solid #dc3545;
                border-radius: 4px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎾 Slot Availability</h1>
                <a href="/" class="back-button">← Back</a>
            </div>
            <p><strong>Time Filter:</strong> {format_time(after_time)} and later</p>
    """

    for i in range(days_count):
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
            html_content += f"""
            <div class="date-header">{label}</div>
            <div class="error">Error fetching availability: {e}</div>
            """
            continue

        html_content += f'<div class="date-header">{label}</div>'

        if not open_slots:
            html_content += f'<div class="no-slots">No open slots after {format_time(after_time)}</div>'
        else:
            by_court = {}
            for s in open_slots:
                by_court.setdefault(s["court"], []).append(s["time"])
            
            for court, times in by_court.items():
                html_content += f'<div class="court-name">🏀 {court}</div>'
                html_content += '<div class="time-slots">'
                for time in times:
                    html_content += f'<div class="time-slot">{format_time(time)}</div>'
                html_content += '</div>'

    html_content += """
        </div>
    </body>
    </html>
    """

    return Response(html_content, mimetype="text/html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
