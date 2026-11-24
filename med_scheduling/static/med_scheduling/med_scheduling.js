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


// Booking and rescheduling (#130): the submit button says the choice made ("Marcar consulta às 09:30");
// each choice carries the words in data-submit-label, and the server writes them for a choice it already knows.
for (const button of document.querySelectorAll("[data-slot-submit]")) {
  const form = button.form;
  if (!form) continue;
  form.addEventListener("change", event => {
    const choice = event.target;
    if (choice.name === "slot" && choice.checked && choice.dataset.submitLabel) {
      button.textContent = choice.dataset.submitLabel;
    }
  });
}

// Booking (#130): the time of a fit-in shows only while "Encaixe" is ticked; the server checks it either way.
for (const box of document.querySelectorAll("[data-fit-in-toggle]")) {
  const only = box.form && box.form.querySelector("[data-fit-in-only]");
  if (!only) continue;
  const fold = () => {
    only.hidden = !box.checked;
    for (const input of only.querySelectorAll("input")) input.disabled = !box.checked;
  };
  box.addEventListener("change", fold);
  fold();
}

// Reception (#129): the board refreshes in place, without reloading the page. It asks the same
// address again, takes the board of the answer and puts it where the old one was, keeping the
// scroll and the focused link or button; it waits while someone types in a field and while the
// tab is hidden, and says what changed in the polite live region. Without this file the page
// stays as it is until "Atualizar", a plain link to itself.
for (const first of document.querySelectorAll("[data-reception-board]")) {
  const seconds = Math.max(15, Number(first.dataset.refreshSeconds) || 60);
  const announce = document.querySelector("[data-reception-announce]");
  let board = first;
  let summary = board.dataset.summary || "";
  let busy = false;

  const typing = () => {
    const active = document.activeElement;
    return Boolean(active && active.closest('input:not([type="hidden"]), select, textarea, [contenteditable]'));
  };
  // A focused link is found again by its address; a button by its form's address and its place in it.
  const placeOf = element => {
    if (!element || !board.contains(element)) return null;
    if (element.matches("a[href]")) return { selector: `a[href="${CSS.escape(element.getAttribute("href"))}"]`, index: 0 };
    const form = element.closest("form[action]");
    if (!form || !element.matches("button")) return null;
    return {
      selector: `form[action="${CSS.escape(form.getAttribute("action"))}"] button`,
      index: [...form.querySelectorAll("button")].indexOf(element),
    };
  };
  const refresh = async asked => {
    if (busy || document.hidden || typing()) return;
    busy = true;
    try {
      const address = window.location.pathname + window.location.search;
      const response = await fetch(address, { credentials: "same-origin", cache: "no-store" });
      // A session that ended answers with the login page: the board stays as it was.
      if (!response.ok || response.redirected) return;
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const fresh = page.querySelector("[data-reception-board]");
      if (!fresh || typing()) return;
      const place = placeOf(document.activeElement);
      const [x, y] = [window.scrollX, window.scrollY];
      const next = document.importNode(fresh, true);
      board.replaceWith(next);
      board = next;
      window.scrollTo(x, y);
      if (place) {
        const again = board.querySelectorAll(place.selector)[place.index];
        if (again) again.focus({ preventScroll: true });
      }
      const text = board.dataset.summary || "";
      if (announce && text && (asked || text !== summary)) announce.textContent = text;
      summary = text;
      bind();
    } catch {
      // Offline or refused: the link "Atualizar" still reloads the page.
    } finally {
      busy = false;
    }
  };
  const bind = () => {
    for (const link of board.querySelectorAll("[data-reception-refresh]")) {
      link.addEventListener("click", event => {
        event.preventDefault();
        refresh(true);
      });
    }
  };
  bind();
  window.setInterval(() => refresh(false), seconds * 1000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh(false);
  });
}
