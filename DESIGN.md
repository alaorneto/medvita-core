---
name: Medvita Core
description: The category standard of a practice-management suite, done with care, on slate neutrals with the Medvita blue only where you act.
colors:
  medvita-blue: "#1273c4"
  medvita-blue-deep: "#0f5ea1"
  medvita-blue-ink: "#0c4c81"
  medvita-blue-mist: "#f3f8fc"
  medvita-blue-night-text: "#418fd0"
  medvita-blue-night-focus: "#5ea0d7"
  medvita-blue-night-mist: "#0e2237"
  slate-ground: "#f8fafc"
  card-white: "#ffffff"
  slate-wash: "#f1f5f9"
  slate-line: "#e2e8f0"
  control-edge: "#7c8ba1"
  slate-strong: "#475569"
  slate-secondary: "#5b6b82"
  slate-disabled: "#94a3b8"
  slate-ink: "#0f172a"
  night-ground: "#0b1120"
  night-card: "#111827"
  night-raised: "#1e293b"
  night-line: "#334155"
  night-edge: "#64748b"
  night-secondary: "#94a3b8"
  night-body: "#e2e8f0"
  night-ink: "#f1f5f9"
  done-fill: "#dcfce7"
  done-text: "#14532d"
  attention-fill: "#fef3c7"
  attention-text: "#92400e"
  attention-solid: "#d97706"
  failed-fill: "#fee2e2"
  failed-text: "#991b1b"
  failed-link: "#b91c1c"
  failed-solid: "#dc2626"
  done-fill-night: "#052e16"
  done-text-night: "#86efac"
  attention-fill-night: "#3b2a06"
  attention-text-night: "#fbbf24"
  failed-fill-night: "#3f0d0d"
  failed-text-night: "#fca5a5"
  failed-link-night: "#f87171"
  type-blue: "#2563eb"
  type-green: "#16a34a"
  type-amber: "#d97706"
  type-red: "#e11d48"
  type-purple: "#7c3aed"
  type-teal: "#0d9488"
  type-gray: "#64748b"
  type-pink: "#db2777"
  type-blue-night: "#60a5fa"
  type-green-night: "#4ade80"
  type-amber-night: "#fbbf24"
  type-red-night: "#fb7185"
  type-purple-night: "#a78bfa"
  type-teal-night: "#2dd4bf"
  type-gray-night: "#94a3b8"
  type-pink-night: "#f472b6"
typography:
  headline:
    fontFamily: "IBM Plex Sans Variable, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: "36px"
    letterSpacing: "-0.015em"
  title:
    fontFamily: "IBM Plex Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: "28px"
    letterSpacing: "-0.015em"
  title-sm:
    fontFamily: "IBM Plex Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: "24px"
    letterSpacing: "-0.015em"
  figure:
    fontFamily: "IBM Plex Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: "32px"
    fontFeature: "\"tnum\""
  body:
    fontFamily: "IBM Plex Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: "24px"
  body-sm:
    fontFamily: "IBM Plex Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "20px"
  section:
    fontFamily: "IBM Plex Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: "20px"
    letterSpacing: "0"
  label:
    fontFamily: "IBM Plex Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: "18px"
    letterSpacing: "0"
  caption:
    fontFamily: "IBM Plex Sans Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: "16px"
  mono:
    fontFamily: "ui-monospace, Cascadia Mono, SF Mono, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: "20px"
rounded:
  marker: "6px"
  control: "8px"
  card: "12px"
  pill: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  2xl: "24px"
  3xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.medvita-blue}"
    textColor: "{colors.card-white}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    typography: "{typography.body-sm}"
  button-primary-hover:
    backgroundColor: "{colors.medvita-blue-deep}"
  button-secondary:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    typography: "{typography.body-sm}"
  button-secondary-hover:
    backgroundColor: "{colors.slate-ground}"
  button-danger:
    backgroundColor: "{colors.failed-solid}"
    textColor: "{colors.card-white}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  button-danger-outline:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.failed-link}"
    rounded: "{rounded.control}"
    padding: "6px 12px"
  button-danger-outline-hover:
    backgroundColor: "{colors.failed-fill}"
  button-ghost:
    textColor: "{colors.medvita-blue-deep}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  button-ghost-hover:
    backgroundColor: "{colors.medvita-blue-mist}"
  state-pill-done:
    backgroundColor: "{colors.done-fill}"
    textColor: "{colors.done-text}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
    typography: "{typography.caption}"
  state-pill-in-progress:
    backgroundColor: "{colors.medvita-blue-mist}"
    textColor: "{colors.medvita-blue-ink}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
    typography: "{typography.caption}"
  state-pill-attention:
    backgroundColor: "{colors.attention-fill}"
    textColor: "{colors.attention-text}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
    typography: "{typography.caption}"
  state-pill-failed:
    backgroundColor: "{colors.failed-fill}"
    textColor: "{colors.failed-text}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
    typography: "{typography.caption}"
  state-pill-inactive:
    backgroundColor: "{colors.slate-ground}"
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
    typography: "{typography.caption}"
  marker:
    backgroundColor: "{colors.slate-ground}"
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.marker}"
    padding: "2px 6px"
    typography: "{typography.caption}"
  card:
    backgroundColor: "{colors.card-white}"
    rounded: "{rounded.card}"
    padding: "24px"
  input:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
    typography: "{typography.body}"
  nav-link:
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
    typography: "{typography.body-sm}"
  nav-link-active:
    backgroundColor: "{colors.medvita-blue-mist}"
    textColor: "{colors.medvita-blue-deep}"
  counter:
    backgroundColor: "{colors.medvita-blue}"
    textColor: "{colors.card-white}"
    rounded: "{rounded.pill}"
    padding: "2px 6px"
    typography: "{typography.caption}"
  slot-option:
    textColor: "{colors.slate-ink}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "44px"
  slot-option-checked:
    backgroundColor: "{colors.medvita-blue-mist}"
    textColor: "{colors.medvita-blue-deep}"
---

# Design System: Medvita Core

## Overview

**Creative North Star: "The Well-Kept Desk"**

Medvita is the category standard of a practice-management suite, executed at full craft and without irony: white cards on a cool slate ground, ink-dark text, one family, thin lines, and the Medvita logo blue only on what can be clicked. Nothing on a screen asks to be decoded. The receptionist sees who is here, with whom, since when and what to do next; the doctor sees the chart and what is permanent. The finish level is set by Linear (density, alignment, keyboard), Stripe Dashboard (tables, states, money) and Nubank (plain Brazilian language and trust); none of them is a look to copy.

The system is dense but calm. Colour carries meaning, never mood: five state tones with one sense each, the brand blue for action, eight appointment-type colours that always travel with the type written beside them. Depth comes from borders; shadows are hairline at most and real only on what floats. Light and dark are the same system with the same token names, dark in slate night. Paper is a first-class output: certificates, prescriptions, encounter copies and receipts print whole, without the app shell.

What this is and is not allowed to be: the Medvita theme (`med_patients/themes/medvita/`) can change only tokens, fonts, logo and CSS over the core's stable component classes (`.card`, `.btn*`, `.badge*`, `.table-scroll`, `.table-stack`, `.page-header`, `.sidebar*`, `.message`, and the rest listed in the core's `docs/ui-design.md`). Layout, screen structure and components belong to the apps' templates and to the Skeleton core. If a screen needs a new arrangement, that is template work in an app, never a theme rule. The direction rejects the decorated medical-SaaS look: gradients, teal washes, stock illustrations, dashboards of vanity numbers.

**Key Characteristics:**
- Slate neutrals, ink text, white cards on a #f8fafc ground; slate night in dark mode.
- The Medvita blue (#1273c4) on primary buttons, links, focus, active navigation, selected options, counters and the in-progress pill, and nowhere else.
- States as soft tinted pills with a dot and dark text; markers as square-cornered labels without a dot.
- One family, IBM Plex Sans (the core's), headings 600, sentence-case labels, tabular numerals.
- 8 px controls, 12 px cards, round pills; borders over shadows.
- Every list stacks into cards on a phone; every document prints whole.

## Colors

A cool slate world with one working blue and five state tones that each say one thing.

The brand blue is not written in `theme.css`. `theme.json` sets `tokens.brand_color: #1273c4` and the core generates the whole `--color-cobalt-50…950` scale from it (step 600 is the colour itself) plus the dark-mode brand tokens, lightened until they reach AA. A clinic with its own colour overrides those tokens and wins by cascade order; `med_patients/tests/test_theme.py` refuses any `--color-cobalt-*`, `--color-brand*`, `--color-fg-brand*` or `--color-focus` declared in the theme CSS.

### Primary
- **Medvita Blue** (medvita-blue): the logo blue, step 600 of the generated scale. Fill of the primary button and the counter, the checkbox/radio accent, the caret, the focus ring in light mode. White on it reads 4.91:1. The same fill in dark mode.
- **Deep Medvita Blue** (medvita-blue-deep, step 700): hover of the primary button (white on it 6.70:1) and, in light mode, the text of every link, ghost button, active tab and active navigation item (6.70:1 on the card, 6.40:1 on the ground).
- **Medvita Blue Ink** (medvita-blue-ink, step 800): text of the in-progress pill and of the info message, on the mist fill (8.30:1).
- **Medvita Blue Mist** (medvita-blue-mist, step 50): the soft fill behind the active navigation item, the info message, the in-progress pill and a checked time slot.
- **Night link and focus** (medvita-blue-night-text, medvita-blue-night-focus, medvita-blue-night-mist): in dark mode links and active items use #418fd0 (5.12:1 on the night card, 5.44:1 on the night ground); the focus ring is step 400 #5ea0d7 (6.32:1 on the card); soft fills are #0e2237 (night link on it 4.66:1).

### Neutral
Light, from ground to ink:
- **Slate Ground** (slate-ground): page background (`--color-canvas`), table head band, inactive pill fill, secondary-soft surfaces.
- **Card White** (card-white): cards, tables, stat tiles, header, inputs, secondary buttons.
- **Slate Wash** (slate-wash): navigation hover, disabled fill, the seal box, subtle dividers inside cards (the lines between items of a list).
- **Slate Line** (slate-line): every structural border: cards, tables, tabs, dividers.
- **Control Edge** (control-edge): the outline of inputs, selects, secondary buttons and time slots, 3.46:1 against white so a field is visible as a field.
- **Slate Strong** (slate-strong): hover border of controls.
- **Slate Secondary** (slate-secondary): secondary text (page metadata, the location line, table head, cell second lines, labels): 5.19:1 on the ground, 5.43:1 on the card, 4.95:1 on the slate wash, so it holds AA on every light surface.
- **Slate Disabled** (slate-disabled): disabled text only.
- **Slate Ink** (slate-ink): both headings and body text (`--color-heading` and `--color-body`): 17.85:1 on the card. Medvita writes body in ink, not in the core's lighter slate-600.

Dark, the same roles in slate night:
- **Night Ground** (night-ground) for the page and the seal box, **Night Card** (night-card) for cards and the header, **Night Raised** (night-raised) for hover, secondary surfaces and the quiet dividers inside a card, **Night Line** (night-line) for every structural border (1.71:1 on the card, visible without shouting), **Night Edge** (night-edge) for control outlines (3.73:1 on the card), **Night Secondary** (night-secondary) for secondary text (6.92:1 on the card, 7.34:1 on the ground), **Night Body** (night-body) for body text (14.39:1), **Night Ink** (night-ink) for headings (16.19:1). Disabled text is #64748b. Shadows switch off on cards.

### State tones
The core's visual vocabulary gives each tone one sense, and Medvita keeps it:

| Tone | Sense | Light (fill / text, ratio) | Dark (fill / text, ratio) |
|---|---|---|---|
| success | working or done | done-fill / done-text, 8.30:1 | done-fill-night / done-text-night, 10.62:1 |
| brand | in progress | medvita-blue-mist / medvita-blue-ink, 8.30:1 | medvita-blue-night-mist / #7ab1de, 7.04:1 |
| warning | asks for attention or an action from the person | attention-fill / attention-text, 6.37:1 | attention-fill-night / attention-text-night, 8.28:1 |
| danger | failed, blocked or irreversible | failed-fill / failed-text, 6.80:1 | failed-fill-night / failed-text-night, 8.68:1 |
| neutral | inactive, closed or draft | slate-ground / slate-ink, 17.06:1 | #0f172a / night-body, 14.48:1 |

- **Failed Solid** (failed-solid) is the fill of the final destructive button in both modes (white on it 4.83:1). **Failed Link** (failed-link, dark failed-link-night) is red text: the danger-outline button and inline errors (6.47:1 light, 6.41:1 dark on the card).
- **Attention Solid** (attention-solid) is the 4 px leading edge of the core's confirmation box.

### Appointment type colours
Eight `--mv-type-*` tokens (type-blue … type-pink, with `-night` variants) paint only the small round swatch (8 px) that leads an appointment in the schedule (`.appt-color-*` sets `--appt-type`; without a type the swatch is the control edge). Against the card they read at least 3.19:1 in light mode (amber, lowest) and at least 6.52:1 in dark mode, enough for a non-text mark. The type is always written in text beside the swatch. When another theme is active, the schedule CSS falls back to the core palette (`var(--mv-type-blue, var(--color-blue-600))`).

### Named Rules
**The Blue Means Act Rule.** The Medvita blue appears only on primary buttons, links, focus rings, the active navigation item and tab, selected options, counters and the in-progress state. Headings, icons at rest, location lines, illustrations and backgrounds are never blue.

**The One Sense Per Tone Rule.** Green is done, blue is in progress, amber asks for the person, red failed or cannot be undone, slate is inactive. A failure is always red; nothing else is.

**The Clinic Wins Rule.** The theme never declares a brand token. The blue comes from `brand_color`, so a practice with its own colour replaces it everywhere at once.

## Typography

**Display Font:** none; there is no display face.
**Body Font:** IBM Plex Sans Variable, the core's (self-hosted, weights 100–700, `font-display: swap`), with `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto` as fallback.
**Label/Mono Font:** the system monospace (`ui-monospace`, Cascadia Mono, SF Mono) for UUIDs, codes and seal digests.

**Character:** one plain, legible grotesque doing every job, distinguished by weight and size rather than by a second family. It already tells l, I and 1 apart, which matters for codes and CPFs read aloud on the phone.

The theme ships no font (`tokens.font: "default"`, `fonts: []`); the scale is the core's, with Medvita's adjustments to headings and labels.

### Hierarchy
- **Headline** (600, 1.75rem / 36px from 640 px, 1.5rem / 32px on phones, −0.015em, balanced wrap): the page `h1`, one per page.
- **Title** (600, 1.125rem / 28px, −0.015em): section `h2`, card titles. The records editor sets its section-card `h2` at 1.0625rem / 24px.
- **Title Small** (600, 1rem / 24px): `h3`, the weekday heads of the week grid. Headings inside a queue card are 0.875rem / 20px, 600.
- **Figure** (600, 1.5rem / 32px, tabular): the value of a stat tile.
- **Body** (400, 1rem / 24px): running text; page descriptions are 0.875rem / 24px on phones and 1rem / 28px from 640 px. Form fields are 16 px on phones (no iOS zoom) and 14 px from 640 px.
- **Body Small** (400, 0.875rem / 20px): tables, metadata values, buttons and navigation links (buttons and links at 500).
- **Section** (600, 0.875rem / 20px, ink, sentence case): the core's section heading, one step above a field label: darker, larger and heavier.
- **Label** (500, 0.8125rem / 18px, no tracking, sentence case, secondary grey): table heads, metadata and field terms, stat labels, the location line, sidebar and dropdown headings. Medvita removes the core's uppercase and tracking from all of them.
- **Caption** (500, 0.75rem / 16px): pills, markers, counters, small buttons, cell second lines (400, 20px), the stacked-table cell label.

### Named Rules
**The One Family Rule.** Everything is IBM Plex Sans; hierarchy comes from 400 / 500 / 600 and size. No heading face, no font file in the theme (the test refuses Inter, Poppins and a display token).

**The Sentence Case Rule.** Labels are written as they are spoken, first letter capital. The theme takes the core's uppercase and wide tracking off every label it styles that way, and no app stylesheet sets uppercase.

**The Tabular Figures Rule.** Times, table cells, metadata values, stat values, queue numbers, time slots and amounts use tabular numerals, so columns of hours and reais line up. Amounts are also right-aligned and never wrap.

## Layout

The shell is the core's: a sticky header, a left rail with the apps (sticky from 1024 px, a collapsible card below), and content on a 4 px grid in a container of up to 1280 px with 16 / 24 / 32 px gutters. Every screen uses the full width of the grid; reading width is limited in the text, not in the card.

A page opens with the core's page header: a location line (the area, or a trail such as "Contas · code", or the day written out), the `h1`, a one-sentence description, and the actions on the right on desktop and below on phones; 32 px (24 px on phones) to the content.

Within an app, columns of cards use `auto-fit` grids: day columns at `minmax(16rem, 1fr)` with 16 px gaps (reception, the finance day, the records day), the week grid at `minmax(11rem, 1fr)` with 12 px gaps. Cards pad 20 px on phones and 24 px from 640 px; table cells pad 12 px vertically and 16 px (20 px from 640 px) horizontally. Frequent actions get 44 px targets (time slots are `min-height: 2.75rem`). The records draft editor keeps its actions in a sticky bar at the bottom, on the ground colour with a top line. A table inside a card is part of the card: it drops its own border, corners and shadow.

**Phones.** Tabs between sibling screens never show a scrollbar; below 640 px, when the strip runs off the screen, its right edge fades out over the last 2rem (a mask, with 2rem of end padding so the last tab clears it). A metadata list stacks each label over its value, with 16 px between pairs. From 640 px the labels take a column as wide as the longest one (at least 9rem, at most 14rem, a long label wraps inside it) and the value starts right after it, on the same baseline: the eye reads label and value as one line, never across half the screen (#143).

**Tables on phones.** Every list is `table-scroll table-stack`. Below 640 px the head hides and each row becomes a card; each cell shows its own label from `data-label` in a 7rem column beside the value (the actions column has `data-label=""`). Medvita keeps that label in sentence case and lets a pill keep its own width instead of stretching. The page never scrolls sideways. A dense table compared line by line may stay scroll-only, inside its card, only with a stated reason (`{# table-scroll only: … #}`); the suite has two.

**Print.** The core hides its shell (`.app-header`, `.app-footer`, `.sidebar-wrapper`); each app hides only navigation by class (`.link-tabs`, `.toolbar`, `.message`, `.<app>-no-print`). Printable documents sit in a `print-page` of 48rem on screen that widens to the paper in print, keep their own header and footer, and set `@page { margin: 18mm 16mm }`. A signature block sits 3rem below the text, 22rem wide, over a 1 px line in the text colour. The sticky editor bar becomes static in print.

The direction's first viewport for the reception (four counts above the day's table) is not built yet: today the reception is three day-column cards (Aguardando, Em atendimento, Próximos) and the arrival queues. Its counts row and table are template work (epic D, #129), not theme work.

### Named Rules
**The No Sideways Page Rule.** A page never scrolls horizontally on a phone: lists stack, and only a declared dense table scrolls inside its card.

**The Whole Document Rule.** Print hides the shell and the navigation by class, never a bare `header`, `footer`, `nav`, `main`, `article` or `section`, so a certificate or receipt keeps its own header and footer.

## Elevation & Depth

Flat by default. Depth is drawn with 1 px lines in slate-line (night-line in dark) and the step from ground to white card, not with shadows. What renders today is the core's hairline shadow: cards, tables and stat tiles carry a barely visible `0 1px 2px` / `0 1px 3px` lift, buttons and inputs a `0 1px 2px` one; in dark mode it disappears into the night. Only floating things (dropdown menus, the account menu, a hovered link card) get a real shadow. The header is the one translucent surface: 90 % of the card colour with an 8 px backdrop blur, from the core.

### Shadow Vocabulary
- **Hairline** (`box-shadow: 0 1px 2px 0 oklch(30% .03 268 / .05), 0 1px 3px 0 oklch(30% .03 268 / .04)`): cards, tables, stat tiles, as compiled in the core.
- **Pop** (`box-shadow: 0 10px 24px -4px #0f172a1f, 0 2px 6px #0f172a14`; dark `0 12px 28px -6px #00000099, 0 2px 6px #00000066`): declared by the theme as `--shadow-pop` for menus and anything that floats.

### Named Rules
**The Borders Over Shadows Rule.** A container is separated by its line and its fill. A shadow larger than a hairline means the thing floats above the page; a card never does.

## Shapes

Gently rounded, never soft. Controls (buttons, inputs, selects, time slots, navigation links, messages, period cards, the voided label) use 8 px (`--radius-base`); cards, tables, stat tiles and the danger zone use 12 px (`--radius-card`); markers and the seal box 6 px. States, counters, avatars and the appointment-type swatch are fully round. Both radii come from the core default (`tokens.radius: "default"`).

Line style carries meaning in the schedule: a solid 1 px border is a period with set hours, a dashed border is a walk-in session card or a period that has ended. An appointment's type is an 8 px round swatch before the written type, never a side stripe. The one coloured edge in the system is the core's own confirmation box (a 4 px amber inline-start edge).

## Components

### Buttons
Quiet and certain: the colour of a button says what it does, never where it sits.
- **Shape:** gently rounded (8 px), 1 px border, 14 / 20 px text at 500, 10 × 16 px padding; small buttons 6 × 12 px at 12 px.
- **Primary:** Medvita Blue fill, white text; at most one per page header or form ("Marcar consulta", "Salvar").
- **Secondary:** white with the control edge and ink text, for neutral, navigational or reversible actions ("Registrar chegada", "Editar").
- **Danger outline:** white with a soft red border and red text, the entry to a destructive action (a row's "Remover", the link to the confirmation page).
- **Danger:** red fill, white text, only for the final submit on the confirmation page.
- **Ghost:** blue text, no border or fill, tertiary actions ("Limpar").
- **Hover / Focus:** primary deepens to step 700, secondary takes the strong border and the wash, danger outline takes the red fill, ghost takes the mist; 150 ms colour transitions. Focus is a 2 px ring in the focus colour, 2 px offset. A submitted form marks its buttons `aria-disabled` (opacity .55), never `disabled`.

### State pills and markers
- **State pill** (`status_badge`): round pill with a 6 px dot in the text colour, a soft fill, a 1 px border of the tone's subtle step, 12 px text at 500. It means a state that changes with time.
- **Marker** (`marker`): square-cornered (6 px) label without a dot, in the tone's fill and border (neutral is the ground fill with the slate line), for a fixed property that changes behaviour: brand ("Principal", "Representante legal"), warning ("Encaixe", "Lotado", "Prioritário"), neutral ("Teleconsulta", "Pessoal", "Compartilhado").
- **Counter:** a full blue pill with white tabular numbers, for counts.
- **How the apps speak it.** The core's `status_badge` and `marker` read fixed maps, so each app's template filter (`patient_state`, `scheduling_state`, `records_state`, `finance_state` and the `*_marker` filters in `med_*/templatetags/`) turns the app's own state into a core code of the same tone, and the label is the app's own: success → `completed`, brand → `running`, warning → `pending`, danger → `failed`, neutral → `withdrawn`; markers brand → `primary`, warning → `locked`, neutral → `private`. An unknown state falls to neutral. The mapping in the build:
  - Patients: active, consent granted, import completed are done; inactive, deceased, consent revoked are neutral; an import uploading, validating or importing is in progress; a validated import waiting for the person is attention; a failed import is red.
  - Scheduling: confirmed and completed are done; arrived (waiting) is attention; in progress is blue; no-show is red; scheduled and cancelled are neutral. Waiting-list waiting is attention, booked is done, cancelled and expired are neutral.
  - Records: signed encounter and issued document are done; drafts and replaced documents are neutral; an active allergy is attention; an active medication is blue, a suspended one attention, an ended one neutral.
  - Finance: open and partially paid charges are attention; paid, registered payment, active price and issued receipt are done; an open cash session is blue; drafts, cancelled, closed, reversed, inactive and voided are neutral.

### Cards / Containers
- **Corner Style:** 12 px.
- **Background:** card white (night card in dark) on the slate ground.
- **Shadow Strategy:** hairline only (see Elevation & Depth).
- **Border:** 1 px slate line.
- **Internal Padding:** 20 px on phones, 24 px from 640 px. Section cards in the records editor carry their title and remove action on one line.

### Inputs / Fields
- **Style:** white fill, 1 px control edge (3.46:1), 8 px corners, 10 × 12 px padding, ink text; 16 px type on phones, 14 px from 640 px. Required fields carry `*`, the others "(opcional)".
- **Focus:** the border turns Medvita Blue with a 3 px ring of the blue at 22 %.
- **Choice of a time** (`slot-option`): a 44 px-tall bordered option; checked, it takes the blue border, the mist fill, blue text at 600, so the choice shows without the radio dot.

### Navigation
- **Left rail:** links at 14 / 20 px, 500, ink text, 8 px corners; hover takes the wash; the current item takes the mist fill, blue text and 600 (`aria-current`). Rail headings are labels in sentence case.
- **Tabs between sibling screens** (`link-tabs`): a bottom-ruled row; the active tab is blue.
- **Location line** (the core's `page-eyebrow`): a quiet trail above the `h1` in secondary grey, 13 px, 500, sentence case; its link turns blue and underlined only on hover. It is a breadcrumb, never a coloured kicker.
- **Header:** the Medvita logo (with its dark variant through `<picture>`); the product name next to it is kept only for screen readers, since the logo already carries the wordmark.

### Icons
One concept, one icon, across the suite and the core (#144). The core draws its own concepts (privacy, configuration, files, transfers, calendar) and its action icons (plus, pencil, trash, search, check); the suite draws the health and front-desk concepts with Tabler Icons v3.52.0 (MIT, `med_patients/LICENSES/tabler-icons.txt`), only the geometry of the icons in use, on the core's grid: 24 px, 1.6 px stroke, round caps. No icon stands for two concepts, and no concept has two icons.
- **Where:** before the label of the main buttons (16 px), of each app's tabs, of the patient tabs and of the "Resumo" panel titles (20 px, in Medvita Blue). Always decorative (`aria-hidden`), always beside the text; an icon never replaces a word. Creating something ("Nova conta", "Novo paciente") takes the core's plus; the other buttons take the icon of the concept they act on ("Registrar chegada" the arrival, "Receber" the payment), or a core action icon (remove, search, print).
- **Map** (`med_patients/templatetags/med_icons.py`): patient `user-heart`, registration `id`, guardians `friends`, coverages `health-recognition`, consents `file-check`, timeline `timeline`; schedule `calendar-user`, appointment `calendar-event`, booking `calendar-plus`, day `calendar-due`, week `calendar-week`, reception `armchair`, arrival `door-enter`, walk-in queue `list-numbers`, waiting list `hourglass`, no-show `user-x`, professional `stethoscope`, room `door`, appointment type `category`, block `calendar-off`, online booking `calendar-share`, telehealth `video`, legal priority `accessible`, fit-in `clock-plus`; chart `report-medical`, encounter `clipboard-heart`, signature `signature`, clinical document `certificate`, allergy `alert-octagon`, medication `pill`, vitals `heartbeat`, diagnosis `list-search`, record template `template`, addendum `file-plus`; consumption `package`, charge `file-invoice`, receipt `receipt`, payment `cash`, cash desk `cash-register`, prices `tag`, daily report `report-money`, receivables `clock-dollar`, reversal `arrow-back-up`, void `receipt-off`; the action `printer`.
- **Not yet:** the core's left rail draws the same cube for every app, and its empty states take only core icons (alaorneto/skeleton#842).

### Tables
- Head band on the slate ground in label type; cells vertically centred; the first column is the item's name as a link; technical codes on a second line (`cell-secondary`), never a `<br>`; numbers right-aligned; dates through `moment`; states only through `status_badge`; actions last, small secondary buttons and a danger-outline one. Phones get the stacked cards described in Layout.

### Appointment line (signature)
An appointment in the schedule is a line led by an 8 px round swatch in its type colour (`--mv-type-*`), with the type name written in secondary grey beside it. The swatch is a reminder; the text is the information.

### Seal and signature (signature, paper)
The seal box of a signed encounter is a quiet panel: the slate wash fill (night ground in dark), a 1 px slate line, 6 px corners, 14 px text, the verification code in monospace that wraps anywhere. An unsigned draft takes the attention tint (amber fill and border, amber text, 6.37:1), because a draft is a state, not a field. A voided receipt carries "Anulado" as a red-tinted label: danger fill, a 1 px danger-medium border, dark red bold text (6.80:1), 8 px corners, next to the receipt number and the reason.

## Do's and Don'ts

### Do:
- **Do** show every state through the app's tone filter and the core's `status_badge` (`{{ code|scheduling_state:"status"|status_badge:label }}`), and every fixed property through `marker`.
- **Do** keep the Medvita blue for primary buttons, links, focus, active navigation and tabs, selected options, counters and the in-progress state.
- **Do** give each region at most one `btn-primary`; open a destructive action with `btn-danger-outline` and finish it with `btn-danger` on the confirmation page.
- **Do** wrap every list in `table-scroll table-stack` with a `data-label` on every cell; declare a scroll-only table with `{# table-scroll only: reason #}`.
- **Do** write dates and times with `|moment`, money with `|brl` in the `amount` class, and numbers in tabular figures.
- **Do** write labels in sentence case at 13 / 18 px.
- **Do** colour app CSS only with tokens (`var(--color-*)`, `var(--mv-type-*)` with a core fallback); a hex value in an app stylesheet fails `tests/test_ui_conventions.py`.
- **Do** write the appointment type beside its colour swatch, and the label beside every pill.
- **Do** give frequent actions a 44 px target.
- **Do** hide shell and navigation in print by class and keep a document's own header, footer and signature block.
- **Do** change the look through the theme's tokens, logo and CSS over the core's component classes; change layout or components in the app's templates.

### Don't:
- **Don't** hand-write a `badge`, `alert`, `empty-state` or `error-summary` in a template; use the core component.
- **Don't** fix a date format (`|date:"d/m/Y"`, `|time:"H:i"`).
- **Don't** label a destructive verb (Remover, Revogar, Excluir, Desativar, Descartar, Anular, Estornar, Encerrar, Cancelar a/o) on a primary, secondary or ghost button.
- **Don't** hide a bare `header`, `footer`, `nav`, `main`, `article` or `section` in a print rule.
- **Don't** paint headings, resting icons, the location line, backgrounds or illustrations in the brand blue.
- **Don't** declare `--color-cobalt-*`, `--color-brand*`, `--color-fg-brand*` or `--color-focus` in the theme CSS; a clinic's own colour must win.
- **Don't** add a second font family or a font file to the theme.
- **Don't** mark an app item's type or state with a coloured side stripe; the type is a round swatch beside its written name.
- **Don't** let colour carry information alone: no swatch without the type, no pill without its label.
- **Don't** separate a card with a shadow larger than a hairline; real shadows are for what floats.
- **Don't** use decorative gradient fills, teal or tinted washes as decoration, stock illustrations, or dashboards of vanity numbers (the edge fade of the phone tab strip is a mask, not a fill).
