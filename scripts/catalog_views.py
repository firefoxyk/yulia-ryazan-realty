"""Build progressive catalog controls from active public records only."""
from html import escape
import json

from property_data import TYPES, MARKETS, plot_sotkas


def controls(records, base):
    if not records:
        return dict(catalog_controls="", catalog_no_results="", catalog_script="")
    rows = []
    for record in records:
        row = {key: record[key] for key in (
            "id", "type", "market", "price", "rooms", "area_m2"
        ) if key in record}
        row["location"] = " ".join(record[key] for key in ("city", "district", "public_address") if key in record)
        if "published_at" in record:
            row["published_at"] = record["published_at"].isoformat()
        if "plot_area" in record:
            row["plot_sotkas"] = float(plot_sotkas(record))
        rows.append(row)
    def options(values):
        return "".join(f'<option value="{escape(str(value), quote=True)}">{escape(label)}</option>' for value, label in values)
    types = options((value, label) for value, label in TYPES.items() if any(row["type"] == value for row in rows))
    markets = options((value, label) for value, label in MARKETS.items() if any(row.get("market") == value for row in rows))
    rooms = options((value, "Студия" if value == 0 else str(value)) for value in sorted({row["rooms"] for row in rows if "rooms" in row}))
    dates = sum("published_at" in row for row in rows)
    newest = ('<option value="newest">Сначала новые' + (' (с датой)' if dates < len(rows) else '') + '</option>') if dates else ""
    date_note = ("Объекты без даты публикации идут после объектов с датой." if dates else "Даты публикации пока не указаны: доступен порядок каталога, без сортировки по новизне.")
    html = f'''<form id="catalog-filters" class="catalog-filters" hidden aria-labelledby="filters-title" novalidate>
      <h2 id="filters-title">Подобрать объект</h2>
      <details class="catalog-disclosure" open><summary>Параметры поиска</summary>
      <div class="catalog-filter-grid">
        <label>Тип недвижимости<select name="type"><option value="">Все типы</option>{types}</select></label>
        <label data-filter-group="market">Рынок<select name="market"><option value="">Любой рынок</option>{markets}</select></label>
        <label class="catalog-location">Город, район или часть адреса<input type="search" name="location" maxlength="200" placeholder="Введите местоположение"></label>
        <label data-filter-group="rooms">Количество комнат<select name="rooms"><option value="">Любое</option>{rooms}</select></label>
        <fieldset data-filter-group="price"><legend>Цена, ₽</legend><div class="catalog-range">
          <label>От<input type="number" name="price_min" min="0" step="1" inputmode="numeric" aria-describedby="price-help catalog-error"></label>
          <label>До<input type="number" name="price_max" min="0" step="1" inputmode="numeric" aria-describedby="price-help catalog-error"></label>
        </div></fieldset>
        <fieldset data-filter-group="area_m2"><legend>Площадь объекта, м²</legend><div class="catalog-range">
          <label>От<input type="number" name="area_min" min="0" step="any" inputmode="decimal" aria-describedby="catalog-error"></label>
          <label>До<input type="number" name="area_max" min="0" step="any" inputmode="decimal" aria-describedby="catalog-error"></label>
        </div></fieldset>
        <fieldset data-filter-group="plot_sotkas"><legend>Площадь участка, сотки</legend><div class="catalog-range">
          <label>От, сот.<input type="number" name="plot_min" min="0" step="any" inputmode="decimal" aria-describedby="plot-help catalog-error"></label>
          <label>До, сот.<input type="number" name="plot_max" min="0" step="any" inputmode="decimal" aria-describedby="plot-help catalog-error"></label>
        </div></fieldset>
      </div>
      <p id="price-help" class="catalog-help">При заданной цене от или до объекты с ценой «по запросу» не показываются.</p>
      <p id="plot-help" class="catalog-help">Площадь участка задаётся в сотках: 1 сотка = 100 м². Можно указать дробное значение.</p>
      <p class="catalog-help">Если выбран параметр, объекты без его значения не показываются. Варианты типа и рынка не сужаются из-за остальных фильтров; рынок и характеристики зависят от выбранного типа.</p>
      <p id="catalog-type-note" class="catalog-help" role="status"></p>
      <div class="catalog-filter-actions"><button class="button button-primary" type="submit">Показать объекты</button><button class="button button-secondary" type="reset">Сбросить фильтры</button></div>
      </details>
      <p id="catalog-error" class="catalog-error" role="alert" hidden></p>
      <div class="catalog-sort"><label>Сортировка<select name="sort"><option value="catalog">Порядок каталога</option>{newest}<option value="price_asc">Сначала дешевле</option><option value="price_desc">Сначала дороже</option></select></label>
      <p class="catalog-help">При сортировке по цене объекты с ценой «по запросу» идут в конце в обоих направлениях. {date_note} При одинаковых значениях сохраняется порядок каталога.</p></div>
      <p id="catalog-count" role="status" aria-live="polite" aria-atomic="true"></p>
    </form>
    <noscript><p class="catalog-help">Все актуальные объекты показаны ниже. Для фильтрации и сортировки включите JavaScript; подробные страницы доступны и без него.</p></noscript>'''
    # Never let public text terminate the inert JSON script element.
    payload = json.dumps(rows, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return dict(
        catalog_controls=html,
        catalog_no_results=f'<div id="catalog-no-results" class="empty-state" hidden><h2>По выбранным параметрам объекты не найдены</h2><p>Попробуйте изменить параметры или расскажите Юлии, что вы ищете.</p><button class="button button-secondary" type="button" data-catalog-reset>Сбросить фильтры</button><a class="text-link" href="{base}contacts/">Связаться с Юлией ↗</a></div>',
        catalog_script=f'<script type="application/json" id="catalog-data">{payload}</script><script src="{base}assets/catalog.js" defer></script>',
    )
