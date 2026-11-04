"""Public property records: TOML validation and selective media access."""
from datetime import date
from decimal import Decimal
from math import isfinite
from pathlib import Path, PurePosixPath
import re
import tomllib
from urllib.parse import urlsplit
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src/data/properties"
MEDIA = ROOT / "src/media/properties"
FIXTURES = ROOT / "tests/fixtures"
TYPES = {"apartment": "Квартира", "house": "Дом", "land": "Земельный участок"}
MARKETS = {"primary": "Первичный рынок", "secondary": "Вторичный рынок"}
STATUSES = {"draft", "active", "sold", "withdrawn"}


def plot_sotkas(record):
    """Convert validated plot data for display/search without changing its source."""
    factor = {"m2": Decimal("0.01"), "sotka": Decimal(1), "ha": Decimal(100)}[record["plot_unit"]]
    return Decimal(str(record["plot_area"])) * factor

AREA_FIELDS = {"area_m2", "plot_area", "rooms", "floor", "floors"}
APPLICABLE = {
    "apartment": {"area_m2", "rooms", "floor", "floors"},
    "house": {"area_m2", "plot_area", "rooms", "floors"},
    "land": {"plot_area"},
}
KEYS = {
    "id", "slug", "status", "ever_published", "published_at", "featured",
    "type", "market", "title", "price", "currency", "city", "district",
    "public_address", "description", "area_m2", "plot_area", "plot_unit",
    "rooms", "floor", "floors", "photos", "cover", "floor_plan",
    "video_url", "tour_url", "features",
}


class PropertyError(ValueError):
    pass


def fail(source, field, message):
    raise PropertyError(f"{source}: поле «{field}»: {message}")


def text(value, source, field):
    if not isinstance(value, str) or not value.strip():
        fail(source, field, "ожидается непустой текст")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        fail(source, field, "недопустимые управляющие символы")
    return value.strip()


def token(value, source, field):
    value = text(value, source, field)
    if len(value) > 80 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        fail(source, field, "только строчные латинские буквы, цифры и дефисы; до 80 символов")
    return value


def number(value, source, field, minimum=0, integer=False):
    try:
        finite = type(value) in (int, float) and isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        fail(source, field, "ожидается конечное число, не логическое значение")
    if integer and type(value) is not int:
        fail(source, field, "ожидается целое число")
    if value < minimum:
        fail(source, field, f"значение должно быть не меньше {minimum}")
    return value


def image_file(value, media_root, source, field):
    value = text(value, source, field)
    parts = PurePosixPath(value).parts
    if (
        not parts or value.startswith("/") or "\\" in value
        or any(part in (".", "..") for part in value.split("/"))
        or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts)
    ):
        fail(source, field, "ожидается относительный путь внутри каталога изображений, без URL и ..")
    root = media_root.resolve()
    if not root.is_relative_to(ROOT):
        fail(source, field, "каталог изображений ведёт за пределы проекта")
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root):
        fail(source, field, "путь или символическая ссылка ведёт за пределы каталога изображений")
    if not candidate.is_file():
        fail(source, field, f"файл не найден: {value}")
    content = candidate.read_bytes()
    suffix = candidate.suffix.lower()
    if suffix == ".svg":
        try:
            tree = ElementTree.fromstring(content)
        except ElementTree.ParseError:
            fail(source, field, "повреждённый SVG")
        allowed = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
        if tree.tag.split("}")[-1] != "svg":
            fail(source, field, "ожидается SVG")
        for node in tree.iter():
            if node.tag.split("}")[-1] not in allowed:
                fail(source, field, "SVG допускает только простые фигуры без скриптов и вложений")
            for name, attribute in node.attrib.items():
                name = name.split("}")[-1].lower()
                if name.startswith("on") or name in ("href", "src", "style") or "url(" in attribute.lower():
                    fail(source, field, "SVG с обработчиками, ссылками или стилями не допускается")
    elif suffix in (".jpg", ".jpeg"):
        if not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
            fail(source, field, "файл не похож на JPEG")
    elif suffix == ".png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            fail(source, field, "файл не похож на PNG")
    elif suffix == ".webp":
        if not (content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
            fail(source, field, "файл не похож на WebP")
    else:
        fail(source, field, "разрешены JPEG, PNG, WebP и простой SVG")
    return value


def external_url(value, source, field):
    value = text(value, source, field)
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
        parsed.port
    except ValueError:
        valid = False
    if not valid or any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
        fail(source, field, "допускается только полный HTTPS-адрес без учётных данных и пробелов")
    return value


def validate(raw, source, media_root, fixture=False):
    if not isinstance(raw, dict):
        fail(source, "record", "ожидается таблица TOML")
    unknown = raw.keys() - KEYS
    if unknown:
        fail(source, sorted(unknown)[0], "неизвестное поле; служебные и личные сведения здесь хранить нельзя")
    data = dict(raw)
    for field in ("id", "slug", "status", "ever_published"):
        if field not in data:
            fail(source, field, "обязательное поле отсутствует")
    for field in ("id", "slug"):
        data[field] = token(data[field], source, field)
    if data["slug"] == "demo":
        fail(source, "slug", "адрес demo зарезервирован существующим деморежимом")
    if not isinstance(data["status"], str) or data["status"] not in STATUSES:
        fail(source, "status", "ожидается draft, active, sold или withdrawn")
    if type(data["ever_published"]) is not bool:
        fail(source, "ever_published", "ожидается true или false")
    if data["status"] == "draft":
        if data["ever_published"]:
            fail(source, "status", "ранее опубликованный объект нельзя молча вернуть в черновик; оставьте публичную запись withdrawn")
        if not fixture:
            fail(source, "status", "непубличный черновик перенесите вне репозитория или в local-private/; публичная сборка его не читает")
    if data["status"] == "active":
        if not data["ever_published"]:
            fail(source, "ever_published", "для текущей публичной публикации укажите true и закрепите id/slug")
        for field in ("type", "title", "city", "description"):
            if field not in data:
                fail(source, field, "обязательное поле для объекта в продаже")
    for field in ("type", "market"):
        if field in data:
            choices = TYPES if field == "type" else MARKETS
            if not isinstance(data[field], str) or data[field] not in choices:
                fail(source, field, "неизвестное значение: " + ", ".join(choices))
    if data.get("type") == "land" and "market" in data:
        fail(source, "market", "первичный/вторичный рынок для участка пока не применяется")
    for field in ("title", "city", "district", "public_address", "description"):
        if field in data:
            data[field] = text(data[field], source, field)
    data.setdefault("featured", False)
    if type(data["featured"]) is not bool:
        fail(source, "featured", "ожидается true или false")
    if "published_at" in data:
        value = data["published_at"]
        try:
            if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                value = date.fromisoformat(value)
            if type(value) is not date:
                raise ValueError()
        except ValueError:
            fail(source, "published_at", "ожидается календарная дата YYYY-MM-DD")
        data["published_at"] = value
    if "price" in data:
        number(data["price"], source, "price", 1, integer=True)
    if data.get("currency", "RUB") != "RUB":
        fail(source, "currency", "на этом этапе поддерживается только RUB")
    for field in AREA_FIELDS & data.keys():
        number(data[field], source, field, 1 if field == "floors" else 0,
               integer=field in ("rooms", "floor", "floors"))
        if field in ("area_m2", "plot_area") and data[field] == 0:
            fail(source, field, "площадь должна быть больше нуля")
        if data.get("type") and field not in APPLICABLE[data["type"]]:
            fail(source, field, "характеристика не применяется к этому типу объекта")
    if "floor" in data and "floors" in data and data["floor"] > data["floors"]:
        fail(source, "floor", "этаж больше этажности здания")
    if "plot_area" in data:
        if data.get("plot_unit") not in ("m2", "sotka", "ha"):
            fail(source, "plot_unit", "укажите m2, sotka или ha")
    elif "plot_unit" in data:
        fail(source, "plot_unit", "единица указана без площади участка")
    data.setdefault("photos", [])
    if not isinstance(data["photos"], list):
        fail(source, "photos", "ожидается список таблиц [[photos]]")
    photos = []
    for index, photo in enumerate(data["photos"]):
        prefix = f"photos[{index}]"
        if not isinstance(photo, dict):
            fail(source, prefix, "ожидается таблица")
        if photo.keys() - {"path", "alt", "caption"}:
            fail(source, prefix, "допустимы только path, alt, caption")
        photos.append(dict(
            path=image_file(photo.get("path"), media_root, source, prefix + ".path"),
            alt=text(photo.get("alt"), source, prefix + ".alt"),
            caption=text(photo["caption"], source, prefix + ".caption") if "caption" in photo else "",
        ))
    data["photos"] = photos
    if "cover" in data:
        number(data["cover"], source, "cover", 0, integer=True)
        if data["cover"] >= len(photos):
            fail(source, "cover", "индекс выходит за пределы списка фотографий")
    else:
        data["cover"] = 0 if photos else None
    if "floor_plan" in data:
        data["floor_plan"] = image_file(data["floor_plan"], media_root, source, "floor_plan")
    for field in ("video_url", "tour_url"):
        if field in data:
            data[field] = external_url(data[field], source, field)
    data.setdefault("features", {})
    if not isinstance(data["features"], dict):
        fail(source, "features", "ожидается таблица текстовых публичных характеристик")
    for label, value in data["features"].items():
        text(label, source, "features")
        text(value, source, "features." + label)
    data.update(_source=str(source), _media_root=media_root, _fixture=fixture)
    return data


def unique(records):
    for field in ("id", "slug"):
        seen = {}
        for record in records:
            value = record[field]
            if value in seen:
                fail(record["_source"], field, f"повтор значения {value}; также в {seen[value]}")
            seen[value] = record["_source"]
    return records


def load_directory(directory, media_root, fixture=False):
    records = []
    for source in sorted(directory.glob("*.toml")):
        if not source.resolve().is_relative_to(directory.resolve()):
            fail(source, "file", "ссылка на TOML ведёт за пределы каталога данных")
        try:
            raw = tomllib.loads(source.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeError) as error:
            fail(source, "TOML", str(error))
        records.append(validate(raw, source, media_root, fixture))
    return unique(records)


def load_catalog(test_data=False):
    records = load_directory(DATA, MEDIA)
    if test_data:
        records += load_directory(FIXTURES / "properties", FIXTURES / "media", fixture=True)
    return unique(records)
