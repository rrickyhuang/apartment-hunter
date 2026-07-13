from __future__ import annotations

import logging
import smtplib
import sqlite3
from email.message import EmailMessage

from jinja2 import Template

from .settings import Settings

log = logging.getLogger(__name__)


def score_color(score) -> str:
    """Red→yellow→green gradient (0–100), matching the map scoreFill function. Grey if None."""
    if score is None:
        return '#94a3b8'
    t = max(0.0, min(1.0, score / 100))
    if t < 0.5:
        s = t / 0.5
        r, g, b = 239, round(68 + (234 - 68) * s), 0
    else:
        s = (t - 0.5) / 0.5
        r = round(250 + (34 - 250) * s)
        g = round(204 + (197 - 204) * s)
        b = round(94 * s)
    return '#{:02x}{:02x}{:02x}'.format(r, g, b)


def _group_by_tier(rows):
    tiers = [
        ('🔥 Hot (≥80)', [r for r in rows if r['score'] is not None and r['score'] >= 80]),
        ('👍 Worth a look (60–79)', [r for r in rows if r['score'] is not None and 60 <= r['score'] < 80]),
        ('🤔 Maybe (40–59)', [r for r in rows if r['score'] is not None and 40 <= r['score'] < 60]),
        ('Other (<40)', [r for r in rows if r['score'] is None or r['score'] < 40]),
    ]
    return [(label, tier_rows) for label, tier_rows in tiers if tier_rows]


EMAIL_TEMPLATE = Template("""\
<html><body style="font-family: -apple-system, Segoe UI, sans-serif; max-width:640px; margin:auto;">
<h2>{{ count }} new apartment match{{ 's' if count != 1 else '' }}</h2>
<p style="color:#666">Score threshold: {{ threshold }}</p>
{% for label, tier_rows in tiers %}
<h3 style="margin:20px 0 8px; border-bottom:2px solid #eee; padding-bottom:4px;">{{ label }}</h3>
{% for row in tier_rows %}
  <div style="border:1px solid #ddd; border-radius:8px; padding:12px; margin:8px 0;">
    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
      <h3 style="margin:0; font-size:15px;"><a href="{{ row['url'] }}" style="color:#1d4ed8; text-decoration:none;">{{ row['title'] }}</a></h3>
      <span style="background:{{ score_color(row['score']) }}; color:white; padding:3px 9px; border-radius:999px; font-size:13px; font-weight:700; white-space:nowrap; margin-left:8px;">
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
{% endfor %}
</body></html>
""")


def render_digest(rows: list, threshold: float) -> str:
    """Render the email HTML without sending. Useful for preview."""
    tiers = _group_by_tier(rows)
    return EMAIL_TEMPLATE.render(
        rows=rows,
        tiers=tiers,
        count=len(rows),
        threshold=int(threshold),
        score_color=score_color,
    )


def send_digest(rows: list[sqlite3.Row], threshold: float) -> bool:
    """Send a digest email of new high-scoring listings.

    Returns True if sent (or no-op when no rows). Raises on SMTP failure.
    """
    if not rows:
        log.info("no new listings above threshold; not sending email")
        return True

    cfg = Settings.load()

    html = render_digest(rows, threshold)

    msg = EmailMessage()
    msg["Subject"] = f"[apartment-hunter] {len(rows)} new match(es)"
    msg["From"] = cfg.gmail_address
    msg["To"] = cfg.alert_to
    msg.set_content(
        "HTML email — open in an HTML-capable client. "
        "Listings:\n" + "\n".join(f"- {r['title']} ({r['url']})" for r in rows)
    )
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(cfg.gmail_address, cfg.gmail_app_password)
        s.send_message(msg)
    log.info("sent digest with %d listings to %s", len(rows), cfg.alert_to)
    return True
