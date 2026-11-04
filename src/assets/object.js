/* Photo links and content work without this progressive enhancement. */
(() => {
  "use strict";
  const share = document.querySelector("[data-object-share]");
  if (share) {
    const copy = share.querySelector("[data-copy-link]");
    const input = share.querySelector("[data-permalink]");
    const label = share.querySelector("[data-permalink-label]");
    const status = share.querySelector("[data-copy-status]");
    input.value = new URL(share.dataset.objectPath, location.origin).href;
    copy.hidden = false;
    copy.addEventListener("click", async () => {
      try {
        if (!window.isSecureContext || !navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(input.value);
        status.textContent = "Ссылка скопирована.";
      } catch {
        label.hidden = false;
        input.hidden = false;
        input.focus();
        input.select();
        status.textContent = "Не удалось скопировать автоматически. Ссылка выделена — скопируйте её вручную.";
      }
    });
  }
  const gallery = document.querySelector("[data-gallery]");
  if (!gallery) return;
  const items = [...gallery.querySelectorAll("[data-gallery-item]")];
  const open = gallery.querySelector("[data-gallery-open]");
  const main = gallery.querySelector("[data-gallery-main]");
  const dialog = gallery.querySelector("dialog");
  const large = dialog.querySelector("[data-dialog-image]");
  let current = Number(gallery.dataset.cover);
  let opener = null;

  function watchImage(image, message) {
    const success = () => { image.hidden = false; message.hidden = true; };
    const failure = () => { image.hidden = true; message.hidden = false; };
    image.addEventListener("load", success);
    image.addEventListener("error", failure);
    if (image.complete && image.getAttribute("src")) {
      if (image.naturalWidth) success(); else failure();
    }
  }
  watchImage(main, gallery.querySelector(".gallery-feature [data-image-error]"));
  watchImage(large, dialog.querySelector("[data-image-error]"));

  function render() {
    const item = items[current];
    const alt = item.querySelector("img").alt;
    const caption = item.dataset.caption;
    const count = `Фото ${current + 1} из ${items.length}`;
    main.src = item.href;
    main.alt = alt;
    open.href = item.href;
    gallery.querySelector("[data-gallery-count]").textContent = count;
    gallery.querySelector("[data-gallery-caption]").textContent = caption;
    for (const link of gallery.querySelectorAll("[data-image-original]")) link.href = item.href;
    for (const [index, link] of items.entries()) {
      if (index === current) link.setAttribute("aria-current", "true");
      else link.removeAttribute("aria-current");
    }
    if (dialog.open) {
      large.src = item.href;
      large.alt = alt;
      dialog.querySelector("[data-dialog-count]").textContent = count;
      dialog.querySelector("[data-dialog-caption]").textContent = caption;
      dialog.querySelector("[data-dialog-original]").href = item.href;
    }
  }
  const move = direction => { current = (current + direction + items.length) % items.length; render(); };
  for (const button of gallery.querySelectorAll("[data-gallery-prev]")) button.addEventListener("click", () => move(-1));
  for (const button of gallery.querySelectorAll("[data-gallery-next]")) button.addEventListener("click", () => move(1));
  for (const [index, item] of items.entries()) item.addEventListener("click", event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    current = index;
    render();
  });
  const controls = gallery.querySelector("[data-gallery-controls]");
  controls.hidden = items.length < 2;
  // Without native modal support, the main image remains a normal file link.
  if (typeof dialog.showModal === "function") {
    open.addEventListener("click", event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      opener = event.currentTarget;
      dialog.showModal();
      document.documentElement.classList.add("photo-dialog-open");
      render();
    });
    dialog.querySelector("[data-gallery-close]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => {
      document.documentElement.classList.remove("photo-dialog-open");
      opener?.focus({preventScroll: true});
    });
    dialog.addEventListener("keydown", event => {
      if (event.key !== "Tab") return;
      const focusable = [...dialog.querySelectorAll("button,a[href]")].filter(element => element.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    });
  }
  gallery.addEventListener("keydown", event => {
    if (items.length < 2 || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault(); move(event.key === "ArrowLeft" ? -1 : 1);
    }
  });
})();
