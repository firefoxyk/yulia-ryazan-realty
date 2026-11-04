/* Progressive enhancement: the static cards remain usable without JavaScript. */
(() => {
  "use strict";
  const form = document.querySelector("#catalog-filters");
  if (!form) return;
  const grid = document.querySelector("#catalog-results");
  const count = document.querySelector("#catalog-count");
  const error = document.querySelector("#catalog-error");
  const noResults = document.querySelector("#catalog-no-results");
  const typeNote = document.querySelector("#catalog-type-note");
  const disclosure = form.querySelector("details");
  const rows = JSON.parse(document.querySelector("#catalog-data").textContent);
  const cards = new Map([...grid.querySelectorAll("[data-property-id]")].map(card => [card.dataset.propertyId, card]));
  // If markup/data are inconsistent, leave the unfiltered static catalog available.
  if (rows.length !== cards.size || rows.some(row => !cards.has(row.id))) return;
  const field = name => form.elements.namedItem(name);
  const normalize = value => value.trim().toLocaleLowerCase("ru").replaceAll("ё", "е").replace(/\s+/g, " ");
  const present = (row, name) => row[name] !== undefined && row[name] !== null;
  const groups = {
    market: ["market"], rooms: ["rooms"], price: ["price_min", "price_max"],
    area_m2: ["area_min", "area_max"], plot_sotkas: ["plot_min", "plot_max"],
  };

  function syncType() {
    const selected = rows.filter(row => !field("type").value || row.type === field("type").value);
    let cleared = false;
    for (const [key, names] of Object.entries(groups)) {
      const available = selected.some(row => present(row, key));
      const group = form.querySelector(`[data-filter-group="${key}"]`);
      group.hidden = !available;
      for (const name of names) {
        const input = field(name);
        input.disabled = !available;
        if (!available && input.value) { input.value = ""; cleared = true; }
      }
      if (key === "market" || key === "rooms") {
        const select = field(key);
        for (const option of select.options) {
          const applicable = !option.value || selected.some(row => String(row[key]) === option.value);
          option.hidden = !applicable;
          option.disabled = !applicable;
        }
        if (select.selectedOptions[0]?.disabled) { select.value = ""; cleared = true; }
      }
    }
    typeNote.textContent = cleared ? "Параметры, неприменимые к выбранному типу, сброшены." : "";
  }

  function range(prefix, label) {
    const inputs = [field(prefix + "_min"), field(prefix + "_max")];
    const values = inputs.map(input => input.disabled || input.value === "" ? null : input.valueAsNumber);
    const invalid = inputs.some((input, index) => !input.disabled &&
      (input.validity.badInput || (values[index] !== null && (!Number.isFinite(values[index]) || values[index] < 0 || input.validity.stepMismatch))));
    const reversed = values[0] !== null && values[1] !== null && values[0] > values[1];
    if (invalid || reversed) {
      for (const input of inputs) if (!input.disabled) input.setAttribute("aria-invalid", "true");
      throw new Error(invalid ? `${label}: введите неотрицательное число${prefix === "price" ? " без копеек" : ""}.` : `${label}: значение «от» не должно превышать значение «до».`);
    }
    return values;
  }

  function matchesRange(row, key, bounds) {
    if (bounds.every(value => value === null)) return true;
    return present(row, key) && (bounds[0] === null || row[key] >= bounds[0]) && (bounds[1] === null || row[key] <= bounds[1]);
  }

  function apply() {
    for (const input of form.querySelectorAll("[aria-invalid]")) input.removeAttribute("aria-invalid");
    error.hidden = true;
    noResults.hidden = true;
    let bounds;
    try {
      bounds = {price: range("price", "Цена"), area_m2: range("area", "Площадь объекта"), plot_sotkas: range("plot", "Площадь участка (сотки)")};
    } catch (problem) {
      error.textContent = problem.message;
      error.hidden = false;
      grid.hidden = true;
      count.textContent = "Проверьте параметры фильтра. Результаты не показаны.";
      return;
    }
    const query = normalize(field("location").value);
    const matched = rows.filter(row => (!field("type").value || row.type === field("type").value) &&
      (!field("market").value || row.market === field("market").value) &&
      (!field("rooms").value || String(row.rooms) === field("rooms").value) &&
      (!query || normalize(row.location).includes(query)) &&
      Object.entries(bounds).every(([key, limits]) => matchesRange(row, key, limits)));
    const sort = field("sort").value;
    matched.sort((a, b) => {
      if (sort === "price_asc" || sort === "price_desc") {
        if (!present(a, "price")) return present(b, "price") ? 1 : 0;
        if (!present(b, "price")) return -1;
        return (a.price - b.price) * (sort === "price_asc" ? 1 : -1);
      }
      if (sort === "newest") {
        if (!a.published_at) return b.published_at ? 1 : 0;
        if (!b.published_at) return -1;
        return b.published_at.localeCompare(a.published_at);
      }
      return 0;
    });
    const visible = new Set(matched.map(row => row.id));
    for (const [id, card] of cards) card.hidden = !visible.has(id);
    // Stable sorting starts from the same server order on every update.
    for (const row of matched) grid.append(cards.get(row.id));
    grid.hidden = !matched.length;
    noResults.hidden = !!matched.length;
    count.textContent = `Найдено объектов: ${matched.length} из ${rows.length}.`;
  }

  form.addEventListener("input", event => {
    if (event.target.tagName === "SELECT") return;
    apply();
  });
  form.addEventListener("change", event => {
    if (event.target.name === "type") syncType();
    apply();
  });
  form.addEventListener("submit", event => { event.preventDefault(); apply(); });
  form.addEventListener("reset", () => requestAnimationFrame(() => { syncType(); apply(); }));
  document.querySelector("[data-catalog-reset]").addEventListener("click", () => {
    form.reset();
    disclosure.open = true;
    field("type").focus();
  });
  syncType();
  apply();
  disclosure.open = window.matchMedia("(min-width: 621px)").matches;
  form.hidden = false;
})();
