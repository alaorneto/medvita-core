---
version: 1
slug: "g-templates-med-scheduling-reception-html-a979da31"
primary_target: "med_scheduling/templates/med_scheduling/reception.html"
related_targets: ["med_patients/themes/medvita/theme.css"]
---

# Medvita Core: app shell and theme (all four apps), led by the reception screen

Scope: the Medvita instance theme (`med_patients/themes/medvita/`) and the apps' own CSS; it reaches every screen of the four apps. Visitor mode: Operate. Primary surface to judge it on: Recepção (`med_scheduling/templates/med_scheduling/reception.html`), then the patient list, the charge page and the encounter editor.

Audience and job: the front desk and the doctor of a small practice, at a shared desk computer and on phones; book, receive, attend, record, get paid in the same day. Constraint: a theme changes tokens, fonts, logo and CSS over the core's stable component classes, never layout or components; screen structure belongs to the apps' templates (epics D and E).

## Direction contract

THESIS: The category standard, done better than the category does it: white cards on a cool slate ground, the logo blue only on what can be clicked, states as soft tinted pills; it refuses the decorated medical-SaaS look (gradients, teal washes, stock illustrations, dashboards of vanity numbers).

OWN-WORLD: Slate neutrals (ground #f8fafc, ink #0f172a, secondary #64748b, lines #e2e8f0), Medvita blue #1273c4 for actions, links and focus only; states in soft fills with dark text (amber attention, blue in progress, green done, slate inactive, red failed). One family, IBM Plex Sans, headings 600; 8 px controls, 12 px cards, borders over shadows. Dark mode the same in slate night.

STORY: The receptionist knows in one glance who is here, with whom, since when and what to do next; nothing asks to be decoded.

FIRST VIEWPORT: Left rail with the apps; page header with the day as h1 and the two desk actions (Registrar chegada secondary, Marcar consulta primary) on the right; a row of four counts (consultas hoje, aguardando, atrasados, recebido hoje); below, the day's table: hora, paciente, profissional, tipo, situação, with the waiting patient rows marked by their attention pill.

FORM: canon (the user's choice on the decision page), seed: 7452818abfcdef15.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Quality bar

Linear, Stripe Dashboard, Nubank: their craft level (alignment, type scale, state clarity, plain language), never their look.

## Unresolved

- The counts row and the day table of the first viewport are template work (epic D, #129); the theme delivers the world they render in.
