"use strict";

// Optional: every page of the scheduling app works without this file; it only saves a click.

// Booking: a duration nobody typed follows the kind picked, as the "Atualizar horários" button
// does on the server. The select carries the duration of each kind it offers.
for (const select of document.querySelectorAll("[data-kind-durations]")) {
  const form = select.form;
  const typed = form && form.querySelector('[data-duration="typed"]');
  const suggested = form && form.querySelector('[data-duration="suggested"]');
  if (!typed || !suggested) continue;
  let durations;
  try {
    durations = JSON.parse(select.dataset.kindDurations);
  } catch {
    continue;
  }
  select.addEventListener("change", () => {
    const minutes = durations[select.value];
    if (minutes === undefined) return;
    if (typed.value === "" || typed.value === suggested.value) typed.value = String(minutes);
    suggested.value = String(minutes);
  });
}

// Periods: "Vagas" is of a walk-in period, so it folds away (and is not sent) in booked time.
// A form with several periods marks each one with data-period.
for (const select of document.querySelectorAll("[data-period-mode]")) {
  const scope = select.closest("[data-period]") || select.form;
  const only = scope ? [...scope.querySelectorAll("[data-walk-in-only]")] : [];
  if (!only.length) continue;
  const fold = () => {
    const walkIn = select.value === "walk_in";
    for (const part of only) {
      part.hidden = !walkIn;
      for (const input of part.querySelectorAll("input")) input.disabled = !walkIn;
    }
  };
  select.addEventListener("change", fold);
  fold();
}

// Periods: the lines after the first stay folded while empty, until asked for.
for (const group of document.querySelectorAll("[data-period-lines]")) {
  const lines = [...group.querySelectorAll("[data-period-line]")];
  const folded = lines.slice(1).filter(line => line.hasAttribute("data-empty"));
  if (!folded.length) continue;
  for (const line of folded) line.hidden = true;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn btn-secondary";
  button.textContent = group.dataset.addLabel || "+";
  lines[lines.length - 1].after(button);
  button.addEventListener("click", () => {
    const line = folded.shift();
    line.hidden = false;
    const input = line.querySelector("input");
    if (input) input.focus();
    if (!folded.length) button.remove();
  });
}
