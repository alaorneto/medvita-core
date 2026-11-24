# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: the small Brazilian practice (consultório) with one to three health professionals and one person at the front desk who also runs the cash desk. The doctor often does everything alone: books, sees the patient, writes the chart and takes the payment. Screens are designed for this practice first; the larger clinic with a dedicated reception, several rooms and a separate finance team is served by the same screens, not the other way around.

Roles inside a practice, as the suite models them (groups Recepção, Profissionais de saúde, Financeiro, plus the owner/administrator):

- **Recepção:** books and reschedules on the phone, registers arrivals, runs the walk-in queue and the waiting list, takes payments and prints receipts. Works with the phone ringing and the patient in front of the desk.
- **Profissional de saúde:** opens the patient, starts or resumes the encounter between consultations, writes the chart, issues certificates and simple prescriptions, signs.
- **Financeiro:** prices, open accounts, daily cash and receivables.
- **Administrador (dono):** sets up the practice, schedules, types of appointment, access and privacy requests.
- **Paciente (portal):** books what a schedule published; reaches the suite only through the patient portal.

## Product Purpose

Medvita Core runs the daily work of a practice in four apps on the Skeleton core: patients (Pacientes), scheduling (Agenda médica), the clinical record (Prontuário) and the front-desk cash (Financeiro). Success is a practice that books, receives, attends, records and gets paid in the same day without paper and without re-typing, with a clinical record that holds up legally.

## Positioning

The four commitments a neighbouring product (iClinic, Feegow, Amplimed) cannot claim together:

1. **A record that holds up in law, explained on the screen.** Sealed encounters and documents, the reading trail, LGPD requests and the 20-year retention are visible where the work happens, in plain Portuguese, not hidden in settings.
2. **Simple at the desk.** Booking, arrival and payment take few steps and no training; the receptionist never has to remember a code or guess what a button does.
3. **Receipts done right.** Numbered, sealed receipts with the amount in words; in Medvita Pro, the Receita Saúde is issued automatically, ending the doctor's manual work.
4. **The practice owns its data.** An open platform (Skeleton) the practice can install, with no lock-in to a vendor.

## Operating Context

- A shared computer at the front desk, often a mid-size laptop or an all-in-one; the doctor's own computer in the consulting room; phones for checking the day. Light and dark mode both in use.
- Printed paper still matters: certificates, simple prescriptions, encounter copies, receipts and the LGPD report handed to the patient.
- Product line: Medvita Core (this repository) is the base; Medvita Pro (Receita Saúde, reminders, ICP-Brasil signature, TISS, online payment) and Medvita Business (NFS-e, telehealth, indicators, stock, interoperability, patient portal, AI assistant) plug in through service APIs, events and registries, never by changing Core's screens directly.

## Capabilities and Constraints

- Server-rendered Django pages on the Skeleton core v0.8.0; JavaScript optional (every page works without it); no CDN.
- Interface uses only the core's component classes and tokens plus each app's own CSS; an instance theme (the Medvita theme ships with `med_patients`) changes tokens, fonts, logo and CSS over stable component classes, never layout or components.
- pt-BR interface text (gettext msgids in pt-BR); dates and times in the practice's time zone; money in integer centavos.
- Personal and health data never in URLs, titles, event payloads, logs or error messages. Nothing is physically deleted.
- Irreversible actions go through a confirmation page; a signed encounter or issued document never changes (addendum or replacement instead).
- Not covered by Core: ICP-Brasil digital signature, controlled-substance prescriptions, TISS, NFS-e, telehealth.

## Brand Commitments

- Name: **Medvita** (the suite: "Medvita Core"). Binding.
- Logo: the Medvita logo from `medvita-design` (`med_patients/themes/medvita/images/logo.svg`, `logo-dark.svg`, `icon.png`). Binding.
- Colours and heading typography: free to change in the new identity. Body font: IBM Plex Sans (the core's), decided.
- Voice: plain, task-first pt-BR; says what happens and what is permanent; never apologises, never vague about errors.
- Visual direction (chosen 2026-11-24 on the decision page): the category standard, executed at full craft, conventions embraced without irony. Craft bar: Linear (density, alignment, keyboard), Stripe Dashboard (tables, states, money), Nubank (plain Brazilian language and trust). These set the finish level, never a look to copy.

## Evidence on Hand

- Demonstration data: `tools/demo_data.py` (fictitious patients, appointments, encounters, charges). No real customers, testimonials or metrics are on hand; none may be invented.
- Brand assets: `med_patients/themes/medvita/images/` (logo, dark logo, icon).

## Product Principles

1. **The desk first.** Every screen answers the receptionist's question at a glance (who, with whom, when, how much) before anything else.
2. **Permanence is visible.** What cannot be undone says so before it happens and shows that it happened.
3. **Never lose what someone typed.** A refusal keeps the input and says how to fix it.
4. **Small practice, no training.** Plain words, few choices per screen, sensible defaults; power comes from shortcuts, not from more options.
5. **Paper is a first-class output.** What a patient takes home is complete, legible and legally sound.

## Accessibility & Inclusion

WCAG 2.2 AA in light and dark mode; keyboard and screen reader use at the desk; 44 px targets for frequent actions; no information by colour alone; text that survives automatic translation (`translate="no"` on codes).
