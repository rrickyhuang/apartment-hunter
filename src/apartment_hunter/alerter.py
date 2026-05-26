from __future__ import annotations

import logging
import os
import smtplib
import sqlite3
from email.message import EmailMessage

from jinja2 import Template

log = logging.getLogger(__name__)


EMAIL_TEMPLATE = Template("""\
<html><body style="font-family: -apple-system, Segoe UI, sans-serif;">
<h2>{{ count }} new apartment match{{ 's' if count != 1 else '' }}</h2>
<p style="color:#666">Score threshold: {{ threshold }}</p>
{% for row in rows %}
  <div style="border:1px solid #ddd; border-radius:8px; padding:12px; margin:12px 0;">
    <div style="display:flex; justify-content:space-between;">
      <h3 style="margin:0;"><a href="{{ row['url'] }}">{{ row['title'] }}</a></h3>
      <span style="background:#2c7; color:white; padding:4px 8px; border-radius:4px;">
        {{ '%.0f'|format(row['score']) }}
      </span>
    </div>
    <p style="margin:6px 0; color:#444;">
      <strong>${{ row['price'] or '?' }}/mo</strong>
      &middot; {{ row['beds'] if row['beds'] is not none else '?' }} bed
      {%- if row['sqft'] %} &middot; {{ row['sqft'] }} sqft{% endif %}
      {%- if row['city'] %} &middot; {{ row['city'] }}{% endif %}
      &middot; <span style="color:#888">{{ row['source'] }}</span>
    </p>
    {% if row['address'] %}<p style="margin:4px 0; color:#666;">{{ row['address'] }}</p>{% endif %}
    {% if row['image_url'] %}
      <img src="{{ row['image_url'] }}" style="max-width:300px; border-radius:4px;" alt="">
    {% endif %}
  </div>
{% endfor %}
</body></html>
""")


def send_digest(rows: list[sqlite3.Row], threshold: float) -> bool:
    """Send a digest email of new high-scoring listings.

    Returns True if sent (or no-op when no rows). Raises on SMTP failure.
    """
    if not rows:
        log.info("no new listings above threshold; not sending email")
        return True

    gmail_addr = os.environ["GMAIL_ADDRESS"]
    gmail_pw = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("ALERT_TO", gmail_addr)

    html = EMAIL_TEMPLATE.render(rows=rows, count=len(rows), threshold=int(threshold))

    msg = EmailMessage()
    msg["Subject"] = f"[apartment-hunter] {len(rows)} new match(es)"
    msg["From"] = gmail_addr
    msg["To"] = recipient
    msg.set_content(
        "HTML email — open in an HTML-capable client. "
        "Listings:\n" + "\n".join(f"- {r['title']} ({r['url']})" for r in rows)
    )
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(gmail_addr, gmail_pw)
        s.send_message(msg)
    log.info("sent digest with %d listings to %s", len(rows), recipient)
    return True
