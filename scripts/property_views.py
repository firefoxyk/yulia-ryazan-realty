"""Small HTML views for validated public records, using the existing design."""
from html import escape
from pathlib import Path
import shutil
from string import Template

from property_data import TYPES, MARKETS, plot_sotkas
from gallery_views import gallery

ROOT = Path(__file__).resolve().parents[1]


def render(template, **values):
    return Template((ROOT / "src/templates" / template).read_text(encoding="utf-8")).substitute(**values)


def address(record, base):
    return f'{base}objects/{record["slug"]}/'


def media_address(record, path, base):
    # Separate namespace prevents a fixture resource from becoming a real image.
    namespace = "test" if record["_fixture"] else "public"
    return f'{base}property-media/{namespace}/{record["id"]}/{path}'


def publish_media(records, output):
    for record in records:
        if record["status"] != "active":
            continue
        paths = [photo["path"] for photo in record["photos"]]
        if "floor_plan" in record:
            paths.append(record["floor_plan"])
        for path in set(paths):
            relative = media_address(record, path, "/").lstrip("/")
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(record["_media_root"] / path, target)


def test_note(record):
    return '<p class="preview-note" data-demo="fixture">Тестовый пример · не реальное объявление.</p>' if record["_fixture"] else ""


def price(record):
    return f'{record["price"]:,}'.replace(",", " ") + " ₽" if "price" in record else "Цена по запросу"


def facts(record, *, plot_in_sotkas=False):
    labels = {"area_m2": "Площадь", "plot_area": "Участок", "rooms": "Комнаты", "floor": "Этаж", "floors": "Этажность"}
    units = {"m2": "м²", "sotka": "сот.", "ha": "га"}
    result = []
    for field, label in labels.items():
        if field in record:
            value = format(record[field], "g")
            if field == "area_m2":
                value += " м²"
            elif field == "plot_area":
                if plot_in_sotkas:
                    value = format(plot_sotkas(record), "f")
                    if "." in value:
                        value = value.rstrip("0").rstrip(".")
                    value = value.replace(".", ",") + " сот."
                else:
                    value += " " + units[record["plot_unit"]]
            elif field == "rooms" and record[field] == 0:
                value = "Студия"
            result.append((label, value))
    result += list(record["features"].items())
    return result


def facts_html(record, limit=None, *, plot_in_sotkas=False):
    pairs = facts(record, plot_in_sotkas=plot_in_sotkas)
    if limit is not None:
        pairs = pairs[:limit]
    if not pairs:
        return ""
    rows = "".join(f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>" for label, value in pairs)
    return f'<dl class="property-facts">{rows}</dl>'


def location(record):
    return ", ".join(record[key] for key in ("city", "district", "public_address") if key in record)


def photo_html(record, base):
    if not record["photos"]:
        return '<div class="property-no-photo">Фотографии пока нет</div>'
    photo = record["photos"][record["cover"]]
    return f'<img src="{media_address(record, photo["path"], base)}" alt="{escape(photo["alt"], quote=True)}" decoding="async">'


def card(record, base, *, plot_in_sotkas=False):
    return render("property-card.html", property_id=record["id"], note=test_note(record),
                  media=photo_html(record, base), price=escape(price(record)),
                  title=escape(record["title"]), location=escape(location(record)),
                  facts=facts_html(record, 3, plot_in_sotkas=plot_in_sotkas), url=address(record, base))


def section(cards, note="", *, base="/", synthetic=False):
    if not cards:
        return ""
    intro = "Посмотрите тестовые примеры оформления. Это не реальные предложения недвижимости." if synthetic else "Посмотрите предложения и откройте подробности, чтобы сравнить варианты с вашими планами."
    return render("property-section.html", cards=cards, note=note, base=base, intro=intro)


def object_page(record, base, phone_href, phone_display):
    if record["status"] in ("sold", "withdrawn"):
        message = "Объект продан" if record["status"] == "sold" else "Объявление снято с публикации"
        return message, render("property-unavailable.html", message=message, base=base, note=test_note(record))
    materials = ""
    if "floor_plan" in record:
        materials += f'<li><a href="{media_address(record, record["floor_plan"], base)}">Планировка</a></li>'
    for field, label in (("video_url", "Видео"), ("tour_url", "Виртуальный тур")):
        if field in record:
            materials += f'<li><a href="{escape(record[field], quote=True)}" rel="noopener noreferrer">{label}</a></li>'
    market = MARKETS[record["market"]] if "market" in record else ""
    category = TYPES[record["type"]] + (" · " + market if market else "")
    published = f'<p>Опубликовано: {record["published_at"].isoformat()}</p>' if "published_at" in record else ""
    return record["title"], render(
        "property.html", base=base, note=test_note(record), category=escape(category),
        title=escape(record["title"]), price=escape(price(record)), location=escape(location(record)),
        gallery=gallery(record, base, media_address), facts=facts_html(record, plot_in_sotkas=True),
        description="".join(f"<p>{escape(line)}</p>" for line in record["description"].splitlines() if line.strip()),
        materials=f'<h2>Дополнительные материалы</h2><ul>{materials}</ul>' if materials else "",
        published=published, phone_href=phone_href, phone_display=phone_display, permalink=address(record, base),
    )
