"use strict";

// Optional: every page of the patients app works without this file. The masks only format while typing;
// the server normalizes and validates what arrives, masked or not (#134).

const MASKS = {
  // 000.000.000-00
  cpf: (digits) => {
    if (digits.length > 11) return null;
    return digits.replace(/^(\d{3})(\d)/, "$1.$2").replace(/^(\d{3})\.(\d{3})(\d)/, "$1.$2.$3").replace(/\.(\d{3})(\d{1,2})$/, ".$1-$2");
  },
  // 00000-000
  cep: (digits) => {
    if (digits.length > 8) return null;
    return digits.replace(/^(\d{5})(\d)/, "$1-$2");
  },
  // (00) 0000-0000 or (00) 00000-0000
  phone: (digits) => {
    if (digits.length > 11) return null;
    if (digits.length <= 2) return digits.length ? `(${digits}` : "";
    const area = digits.slice(0, 2);
    const rest = digits.slice(2);
    const split = digits.length === 11 ? 5 : 4;
    return rest.length > split ? `(${area}) ${rest.slice(0, split)}-${rest.slice(split)}` : `(${area}) ${rest}`;
  },
};

for (const input of document.querySelectorAll("input[data-mask]")) {
  const mask = MASKS[input.dataset.mask];
  if (!mask) continue;
  const apply = (force) => {
    const value = input.value;
    // Something other than digits and the mask's own signs (a "+55", a letter) is left as typed.
    if (/[^\d.\-() ]/.test(value)) return;
    // Formatting mid-text would move the caret; that waits for the field to lose focus.
    if (!force && input.selectionStart !== value.length) return;
    const formatted = mask(value.replace(/\D/g, ""));
    if (formatted !== null && formatted !== value) input.value = formatted;
  };
  input.addEventListener("input", () => apply(false));
  input.addEventListener("blur", () => apply(true));
}

// Import in progress: the status region refreshes itself, as the "Atualizar" link does. When the batch leaves
// the running states, the whole page reloads so its next step (mapping, "Importar", report) appears.
const region = document.querySelector("[data-import-poll]");
if (region && region.id && window.fetch && window.DOMParser) {
  const started = Date.now();
  const every = 4000;
  const limit = 15 * 60 * 1000;
  const poll = async () => {
    if (Date.now() - started > limit) return;
    if (document.hidden) {
      setTimeout(poll, every);
      return;
    }
    try {
      const response = await fetch(window.location.href, { credentials: "same-origin", headers: { Accept: "text/html" } });
      if (!response.ok) return;
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const fresh = page.getElementById(region.id);
      if (!fresh) return;
      const now = [...region.children];
      const next = [...fresh.children];
      if (!fresh.hasAttribute("data-import-poll") || now.length !== next.length) {
        window.location.reload();
        return;
      }
      // The live line stays the same element (so a screen reader hears the change); the rest is swapped.
      now.forEach((element, index) => {
        const update = next[index];
        if (element.hasAttribute("data-import-live")) {
          if (element.innerHTML !== update.innerHTML) element.innerHTML = update.innerHTML;
        } else {
          element.replaceWith(document.importNode(update, true));
        }
      });
    } catch {
      return; // Offline or the session ended: the "Atualizar" link still works.
    }
    setTimeout(poll, every);
  };
  setTimeout(poll, every);
}
