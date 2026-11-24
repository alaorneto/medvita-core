"""One icon per concept of the suite, and one concept per icon (#144).

The core maps its own concepts (``skeleton/web/icons.py``, #768 of the core): people, calendar,
files, audit, privacy, configuration... The suite's health and front-desk concepts have no core
icon, so they get one here, drawn from Tabler Icons v3.52.0 (MIT, ``med_patients/LICENSES/
tabler-icons.txt``): only the geometry of the icons in use, rendered with the core's stroke
(24 px, 1.6) so both sets read as one. A suite concept that IS a core concept (privacy, import,
audit trail, attachments, configuration) is the core concept: ``med_icon`` draws it with the
core's own component (``"privacy"|concept_icon``), so a tab row or a toolbar can mix both.

Templates write the concept, never the icon: ``{% load med_icons %}{% med_icon "encounter" %}``,
or ``{% med_icon tab.icon "size-4" %}`` with a concept held in data (a patient tab).
``tests/test_icons.py`` checks that the map is one-to-one, that no suite concept is a core
concept, that every icon has its shapes and that templates name concepts, not icons.
"""

from __future__ import annotations

from functools import cache

from django import template
from django.template import Context, Template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

# Concept of the suite -> Tabler icon. Grouped by the app that owns the concept.
MED_CONCEPT_ICONS: dict[str, str] = {
    # Patients.
    "patient": "user-heart",
    "patient_registration": "id",
    "guardians": "friends",
    "coverages": "health-recognition",
    "consents": "file-check",
    "timeline": "timeline",
    # Scheduling.
    "schedule": "calendar-user",
    "appointment": "calendar-event",
    "booking": "calendar-plus",
    "day": "calendar-due",
    "week": "calendar-week",
    "reception": "armchair",
    "arrival": "door-enter",
    "walk_in_queue": "list-numbers",
    "waitlist": "hourglass",
    "no_show": "user-x",
    "professional": "stethoscope",
    "room": "door",
    "appointment_type": "category",
    "block": "calendar-off",
    "online_booking": "calendar-share",
    "telehealth": "video",
    "legal_priority": "accessible",
    "fit_in": "clock-plus",
    # Clinical record.
    "chart": "report-medical",
    "encounter": "clipboard-heart",
    "signature": "signature",
    "clinical_document": "certificate",
    "allergy": "alert-octagon",
    "medication": "pill",
    "vitals": "heartbeat",
    "diagnosis": "list-search",
    "record_template": "template",
    "addendum": "file-plus",
    "consumption": "package",
    # Front-desk cash.
    "charge": "file-invoice",
    "receipt": "receipt",
    "payment": "cash",
    "cash_desk": "cash-register",
    "prices": "tag",
    "daily_report": "report-money",
    "receivables": "clock-dollar",
    "reversal": "arrow-back-up",
    "void": "receipt-off",
}

# Actions of the suite that the core's action set does not draw (the core's are used as they are).
MED_ACTION_ICONS: frozenset[str] = frozenset({"printer"})
# The core's action icons the suite's buttons use, drawn by its component by name (its map is not
# a public surface; tests/test_icons.py checks these are in it).
CORE_ACTION_ICONS: frozenset[str] = frozenset(
    {
        "plus",
        "pencil",
        "trash",
        "restore",
        "search",
        "filter",
        "check",
        "check-circle",
        "eye",
        "chevron-left",
        "chevron-right",
    }
)

ICON_SHAPES: dict[str, str] = {
    "accessible": '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0"/><path d="M10 16.5l2 -3l2 3m-2 -3v-2l3 -1m-6 0l3 1"/><path d="M11.5 7.5a.5 .5 0 1 0 1 0a.5 .5 0 1 0 -1 0"/>',
    "alert-octagon": '<path d="M3 9.101v5.798c0 .53 .211 1.039 .586 1.415l4.1 4.1c.375 .375 .884 .586 1.415 .586h5.799c.53 0 1.039 -.211 1.414 -.586l4.1 -4.1c.375 -.375 .586 -.884 .586 -1.415v-5.798c0 -.53 -.211 -1.039 -.586 -1.415l-4.1 -4.1c-.375 -.375 -.884 -.586 -1.414 -.586l-5.799 0c-.53 0 -1.039 .211 -1.415 .586l-4.1 4.1c-.375 .375 -.586 .884 -.586 1.415"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    "armchair": '<path d="M5 11a2 2 0 0 1 2 2v2h10v-2a2 2 0 1 1 4 0v4a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-4a2 2 0 0 1 2 -2"/><path d="M5 11v-5a3 3 0 0 1 3 -3h8a3 3 0 0 1 3 3v5"/><path d="M6 19v2"/><path d="M18 19v2"/>',
    "arrow-back-up": '<path d="M9 14l-4 -4l4 -4"/><path d="M5 10h11a4 4 0 1 1 0 8h-1"/>',
    "calendar-due": '<path d="M4 7a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2l0 -12"/><path d="M16 3v4"/><path d="M8 3v4"/><path d="M4 11h16"/><path d="M11 16a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/>',
    "calendar-event": '<path d="M4 7a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2l0 -12"/><path d="M16 3l0 4"/><path d="M8 3l0 4"/><path d="M4 11l16 0"/><path d="M8 15h2v2h-2l0 -2"/>',
    "calendar-off": '<path d="M9 5h9a2 2 0 0 1 2 2v9m-.184 3.839a2 2 0 0 1 -1.816 1.161h-12a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 1.158 -1.815"/><path d="M16 3v4"/><path d="M8 3v1"/><path d="M4 11h7m4 0h5"/><path d="M3 3l18 18"/>',
    "calendar-plus": '<path d="M12.5 21h-6.5a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v5"/><path d="M16 3v4"/><path d="M8 3v4"/><path d="M4 11h16"/><path d="M16 19h6"/><path d="M19 16v6"/>',
    "calendar-share": '<path d="M12 21h-6a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v6"/><path d="M16 3v4"/><path d="M8 3v4"/><path d="M4 11h16"/><path d="M16 22l5 -5"/><path d="M21 21.5v-4.5h-4.5"/>',
    "calendar-user": '<path d="M12 21h-6a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v4.5"/><path d="M16 3v4"/><path d="M8 3v4"/><path d="M4 11h16"/><path d="M17 17a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M22 22a2 2 0 0 0 -2 -2h-2a2 2 0 0 0 -2 2"/>',
    "calendar-week": '<path d="M4 7a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2v-12"/><path d="M16 3v4"/><path d="M8 3v4"/><path d="M4 11h16"/><path d="M7 14h.013"/><path d="M10.01 14h.005"/><path d="M13.01 14h.005"/><path d="M16.015 14h.005"/><path d="M13.015 17h.005"/><path d="M7.01 17h.005"/><path d="M10.01 17h.005"/>',
    "cash-register": '<path d="M21 15h-2.5c-.398 0 -.779 .158 -1.061 .439c-.281 .281 -.439 .663 -.439 1.061c0 .398 .158 .779 .439 1.061c.281 .281 .663 .439 1.061 .439h1c.398 0 .779 .158 1.061 .439c.281 .281 .439 .663 .439 1.061c0 .398 -.158 .779 -.439 1.061c-.281 .281 -.663 .439 -1.061 .439h-2.5"/><path d="M19 21v1m0 -8v1"/><path d="M13 21h-7c-.53 0 -1.039 -.211 -1.414 -.586c-.375 -.375 -.586 -.884 -.586 -1.414v-10c0 -.53 .211 -1.039 .586 -1.414c.375 -.375 .884 -.586 1.414 -.586h2m12 3.12v-1.12c0 -.53 -.211 -1.039 -.586 -1.414c-.375 -.375 -.884 -.586 -1.414 -.586h-2"/><path d="M16 10v-6c0 -.53 -.211 -1.039 -.586 -1.414c-.375 -.375 -.884 -.586 -1.414 -.586h-4c-.53 0 -1.039 .211 -1.414 .586c-.375 .375 -.586 .884 -.586 1.414v6m8 0h-8m8 0h1m-9 0h-1"/><path d="M8 14v.01"/><path d="M8 17v.01"/><path d="M12 13.99v.01"/><path d="M12 17v.01"/>',
    "cash": '<path d="M7 15h-3a1 1 0 0 1 -1 -1v-8a1 1 0 0 1 1 -1h12a1 1 0 0 1 1 1v3"/><path d="M7 10a1 1 0 0 1 1 -1h12a1 1 0 0 1 1 1v8a1 1 0 0 1 -1 1h-12a1 1 0 0 1 -1 -1l0 -8"/><path d="M12 14a2 2 0 1 0 4 0a2 2 0 0 0 -4 0"/>',
    "category": '<path d="M4 4h6v6h-6l0 -6"/><path d="M14 4h6v6h-6l0 -6"/><path d="M4 14h6v6h-6l0 -6"/><path d="M14 17a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"/>',
    "certificate": '<path d="M12 15a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"/><path d="M13 17.5v4.5l2 -1.5l2 1.5v-4.5"/><path d="M10 19h-5a2 2 0 0 1 -2 -2v-10c0 -1.1 .9 -2 2 -2h14a2 2 0 0 1 2 2v10a2 2 0 0 1 -1 1.73"/><path d="M6 9l12 0"/><path d="M6 12l3 0"/><path d="M6 15l2 0"/>',
    "clipboard-heart": '<path d="M9 5h-2a2 2 0 0 0 -2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-12a2 2 0 0 0 -2 -2h-2"/><path d="M9 5a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2a2 2 0 0 1 -2 2h-2a2 2 0 0 1 -2 -2"/><path d="M11.993 16.75l2.747 -2.815a1.9 1.9 0 0 0 0 -2.632a1.775 1.775 0 0 0 -2.56 0l-.183 .188l-.183 -.189a1.775 1.775 0 0 0 -2.56 0a1.899 1.899 0 0 0 0 2.632l2.738 2.825l.001 -.009"/>',
    "clock-dollar": '<path d="M20.866 10.45a9 9 0 1 0 -7.815 10.488"/><path d="M12 7v5l1.5 1.5"/><path d="M21 15h-2.5a1.5 1.5 0 0 0 0 3h1a1.5 1.5 0 0 1 0 3h-2.5"/><path d="M19 21v1m0 -8v1"/>',
    "clock-plus": '<path d="M20.984 12.535a9 9 0 1 0 -8.468 8.45"/><path d="M16 19h6"/><path d="M19 16v6"/><path d="M12 7v5l3 3"/>',
    "door-enter": '<path d="M13 12v.01"/><path d="M3 21h18"/><path d="M5 21v-16a2 2 0 0 1 2 -2h6m4 10.5v7.5"/><path d="M21 7h-7m3 -3l-3 3l3 3"/>',
    "door": '<path d="M14 12v.01"/><path d="M3 21h18"/><path d="M6 21v-16a2 2 0 0 1 2 -2h8a2 2 0 0 1 2 2v16"/>',
    "file-check": '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2"/><path d="M9 15l2 2l4 -4"/>',
    "file-invoice": '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2"/><path d="M9 7l1 0"/><path d="M9 13l6 0"/><path d="M13 17l2 0"/>',
    "file-plus": '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2"/><path d="M12 11l0 6"/><path d="M9 14l6 0"/>',
    "friends": '<path d="M5 5a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M5 22v-5l-1 -1v-4a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v4l-1 1v5"/><path d="M15 5a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M15 22v-4h-2l2 -6a1 1 0 0 1 1 -1h2a1 1 0 0 1 1 1l2 6h-2v4"/>',
    "health-recognition": '<path d="M4 8v-2a2 2 0 0 1 2 -2h2"/><path d="M4 16v2a2 2 0 0 0 2 2h2"/><path d="M16 4h2a2 2 0 0 1 2 2v2"/><path d="M16 20h2a2 2 0 0 0 2 -2v-2"/><path d="M8.603 9.61a2.04 2.04 0 0 1 2.912 0l.485 .39l.5 -.396a2.035 2.035 0 0 1 2.897 .007a2.104 2.104 0 0 1 0 2.949l-3.397 3.44l-3.397 -3.44a2.104 2.104 0 0 1 0 -2.95"/>',
    "heartbeat": '<path d="M19.5 13.572l-7.5 7.428l-2.896 -2.868m-6.117 -8.104a5 5 0 0 1 9.013 -3.022a5 5 0 1 1 7.5 6.572"/><path d="M3 13h2l2 3l2 -6l1 3h3"/>',
    "hourglass": '<path d="M6.5 7h11"/><path d="M6.5 17h11"/><path d="M6 20v-2a6 6 0 1 1 12 0v2a1 1 0 0 1 -1 1h-10a1 1 0 0 1 -1 -1"/><path d="M6 4v2a6 6 0 1 0 12 0v-2a1 1 0 0 0 -1 -1h-10a1 1 0 0 0 -1 1"/>',
    "id": '<path d="M3 7a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v10a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3l0 -10"/><path d="M7 10a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M15 8l2 0"/><path d="M15 12l2 0"/><path d="M7 16l10 0"/>',
    "list-numbers": '<path d="M11 6h9"/><path d="M11 12h9"/><path d="M12 18h8"/><path d="M4 16a2 2 0 1 1 4 0c0 .591 -.5 1 -1 1.5l-3 2.5h4"/><path d="M6 10v-6l-2 2"/>',
    "list-search": '<path d="M11 15a4 4 0 1 0 8 0a4 4 0 1 0 -8 0"/><path d="M18.5 18.5l2.5 2.5"/><path d="M4 6h16"/><path d="M4 12h4"/><path d="M4 18h4"/>',
    "package": '<path d="M12 3l8 4.5l0 9l-8 4.5l-8 -4.5l0 -9l8 -4.5"/><path d="M12 12l8 -4.5"/><path d="M12 12l0 9"/><path d="M12 12l-8 -4.5"/><path d="M16 5.25l-8 4.5"/>',
    "pill": '<path d="M4.5 12.5l8 -8a4.94 4.94 0 0 1 7 7l-8 8a4.94 4.94 0 0 1 -7 -7"/><path d="M8.5 8.5l7 7"/>',
    "printer": '<path d="M17 17h2a2 2 0 0 0 2 -2v-4a2 2 0 0 0 -2 -2h-14a2 2 0 0 0 -2 2v4a2 2 0 0 0 2 2h2"/><path d="M17 9v-4a2 2 0 0 0 -2 -2h-6a2 2 0 0 0 -2 2v4"/><path d="M7 15a2 2 0 0 1 2 -2h6a2 2 0 0 1 2 2v4a2 2 0 0 1 -2 2h-6a2 2 0 0 1 -2 -2l0 -4"/>',
    "receipt-off": '<path d="M5 21v-16m2 -2h10a2 2 0 0 1 2 2v10m0 4.01v1.99l-3 -2l-2 2l-2 -2l-2 2l-2 -2l-3 2"/><path d="M11 7l4 0"/><path d="M9 11l2 0"/><path d="M13 15l2 0"/><path d="M15 11l0 .01"/><path d="M3 3l18 18"/>',
    "receipt": '<path d="M5 21v-16a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v16l-3 -2l-2 2l-2 -2l-2 2l-2 -2l-3 2m4 -14h6m-6 4h6m-2 4h2"/>',
    "report-medical": '<path d="M9 5h-2a2 2 0 0 0 -2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-12a2 2 0 0 0 -2 -2h-2"/><path d="M9 5a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2a2 2 0 0 1 -2 2h-2a2 2 0 0 1 -2 -2"/><path d="M10 14l4 0"/><path d="M12 12l0 4"/>',
    "report-money": '<path d="M9 5h-2a2 2 0 0 0 -2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-12a2 2 0 0 0 -2 -2h-2"/><path d="M9 5a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2a2 2 0 0 1 -2 2h-2a2 2 0 0 1 -2 -2"/><path d="M14 11h-2.5a1.5 1.5 0 0 0 0 3h1a1.5 1.5 0 0 1 0 3h-2.5"/><path d="M12 17v1m0 -8v1"/>',
    "signature": '<path d="M3 17c3.333 -3.333 5 -6 5 -8c0 -3 -1 -3 -2 -3s-2.032 1.085 -2 3c.034 2.048 1.658 4.877 2.5 6c1.5 2 2.5 2.5 3.5 1l2 -3c.333 2.667 1.333 4 3 4c.53 0 2.639 -2 3 -2c.517 0 1.517 .667 3 2"/>',
    "stethoscope": '<path d="M6 4h-1a2 2 0 0 0 -2 2v3.5a5.5 5.5 0 0 0 11 0v-3.5a2 2 0 0 0 -2 -2h-1"/><path d="M8 15a6 6 0 1 0 12 0v-3"/><path d="M11 3v2"/><path d="M6 3v2"/><path d="M18 10a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/>',
    "tag": '<path d="M6.5 7.5a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/><path d="M3 6v5.172a2 2 0 0 0 .586 1.414l7.71 7.71a2.41 2.41 0 0 0 3.408 0l5.592 -5.592a2.41 2.41 0 0 0 0 -3.408l-7.71 -7.71a2 2 0 0 0 -1.414 -.586h-5.172a3 3 0 0 0 -3 3"/>',
    "template": '<path d="M4 5a1 1 0 0 1 1 -1h14a1 1 0 0 1 1 1v2a1 1 0 0 1 -1 1h-14a1 1 0 0 1 -1 -1l0 -2"/><path d="M4 13a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v6a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1l0 -6"/><path d="M14 12l6 0"/><path d="M14 16l6 0"/><path d="M14 20l6 0"/>',
    "timeline": '<path d="M4 16l6 -7l5 5l5 -6"/><path d="M14 14a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/><path d="M9 9a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/><path d="M3 16a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/><path d="M19 8a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/>',
    "user-heart": '<path d="M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0"/><path d="M6 21v-2a4 4 0 0 1 4 -4h.5"/><path d="M18 22l3.35 -3.284a2.143 2.143 0 0 0 .005 -3.071a2.242 2.242 0 0 0 -3.129 -.006l-.224 .22l-.223 -.22a2.242 2.242 0 0 0 -3.128 -.006a2.143 2.143 0 0 0 -.006 3.071l3.355 3.296"/>',
    "user-x": '<path d="M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0"/><path d="M6 21v-2a4 4 0 0 1 4 -4h3.5"/><path d="M22 22l-5 -5"/><path d="M17 22l5 -5"/>',
    "video": '<path d="M15 10l4.553 -2.276a1 1 0 0 1 1.447 .894v6.764a1 1 0 0 1 -1.447 .894l-4.553 -2.276v-4"/><path d="M3 8a2 2 0 0 1 2 -2h8a2 2 0 0 1 2 2v8a2 2 0 0 1 -2 2h-8a2 2 0 0 1 -2 -2l0 -8"/>',
}


def icon_markup(name: str, css_class: str = "size-5") -> str:
    """The decorative SVG of one suite icon (empty for an unknown one: the tests refuse it)."""
    shapes = ICON_SHAPES.get(name)
    if shapes is None:
        return ""
    return format_html(
        '<svg aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg" fill="none" '
        'viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
        'stroke-linejoin="round" class="{}">{}</svg>',
        css_class,
        mark_safe(shapes),  # noqa: S308 - fixed geometry from ICON_SHAPES, never user input.
    )


@cache
def _core_icon() -> Template:
    return Template(
        "{% load skeleton_format %}{% with name=concept|concept_icon %}{% if name %}"
        '{% include "skeleton/web/components/icon.html" with name=name class=css_class %}'
        "{% endif %}{% endwith %}"
    )


def core_concept_markup(concept: str, css_class: str = "size-5") -> str:
    """The core's icon of one of its concepts, through its public filter and component; empty if unknown."""
    return mark_safe(_core_icon().render(Context({"concept": concept, "css_class": css_class})).strip())  # noqa: S308


@register.simple_tag
def med_icon(concept: str, css_class: str = "size-5") -> str:
    """The icon of a concept: ``{% med_icon "encounter" %}``, or of a core one (``"privacy"``)."""
    if concept in MED_CONCEPT_ICONS:
        return icon_markup(MED_CONCEPT_ICONS[concept], css_class)
    return core_concept_markup(concept, css_class) if concept else ""


@cache
def _core_action() -> Template:
    return Template('{% include "skeleton/web/components/icon.html" with name=name class=css_class %}')


@register.simple_tag
def med_action_icon(action: str, css_class: str = "size-5") -> str:
    """An action icon: the suite's (``printer``) or one of ``CORE_ACTION_ICONS``, drawn by the core."""
    if action in MED_ACTION_ICONS:
        return icon_markup(action, css_class)
    if action in CORE_ACTION_ICONS:
        return mark_safe(_core_action().render(Context({"name": action, "css_class": css_class})).strip())  # noqa: S308
    return ""
