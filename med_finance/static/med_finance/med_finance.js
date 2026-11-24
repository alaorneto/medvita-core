"use strict";

// Optional: every page of the finance app works without this file; it only saves a look and a click.

// Payment (#132): installments and the authorization code belong to the cards. A field marked with
// data-payment-only="<methods>" folds away (and is not sent) for the other methods; without this
// script every field shows and the server validates them.
for (const select of document.querySelectorAll("select[data-payment-method]")) {
  const form = select.form;
  const only = form ? [...form.querySelectorAll("[data-payment-only]")] : [];
  if (!only.length) continue;
  const fold = () => {
    for (const input of only) {
      const shown = input.dataset.paymentOnly.split(" ").includes(select.value);
      const wrapper = input.closest(".form-field") || input;
      wrapper.hidden = !shown;
      input.disabled = !shown;
    }
  };
  select.addEventListener("change", fold);
  fold();
}

// Printing: a button that opens the browser's print dialog, shown only when this script runs.
for (const button of document.querySelectorAll("button[data-print]")) {
  button.hidden = false;
  button.addEventListener("click", () => window.print());
}
