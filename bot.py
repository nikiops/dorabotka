import asyncio
import os
import random
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, MutableMapping, cast

from PIL import Image, ImageDraw, ImageFont, ImageOps
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    pytesseract = cast(Any, import_module("pytesseract"))
except ImportError:
    pytesseract = None

try:
    np = cast(Any, import_module("numpy"))
    RapidOCR = cast(Any, import_module("rapidocr_onnxruntime").RapidOCR)
except ImportError:
    np = None
    RapidOCR = None


TOKEN = os.getenv("TELEGRAM_TOKEN", "7946181504:AAFq657zW04cOXULn7oKMKOeCzyg3vRDl1A")

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(BASE_DIR / "output")))
OUTPUT_DIR.mkdir(exist_ok=True)

DEFAULT_NOMBRE_ORIGEN = os.getenv(
    "DEFAULT_NOMBRE_ORIGEN",
    "Lema Gavilanes Martha Alexandra",
)


def sanitize_account_number(raw_value: str) -> str:
    digits = re.sub(r"\D", "", raw_value or "")
    return digits if len(digits) == 10 else "2207031220"


DEFAULT_CUENTA_ORIGEN = sanitize_account_number(
    os.getenv("DEFAULT_CUENTA_ORIGEN", "2207031220")
)

MONTHS_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}

PRIMARY_COLOR = (20, 24, 28)
SECONDARY_COLOR = (92, 92, 92)
CENTER_X = 296
LEFT_X = 62
RIGHT_X = 532
RESAMPLING_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
RESAMPLING_BICUBIC = getattr(getattr(Image, "Resampling", Image), "BICUBIC")
JOKE_WATERMARK_TEXT = os.getenv("JOKE_WATERMARK_TEXT", "JOKE / DEMO / NO VALIDO")
ENABLE_JOKE_WATERMARK = os.getenv("ENABLE_JOKE_WATERMARK", "1") != "0"

FONT_PATHS = {
    "regular": [
        BASE_DIR / "fonts" / "Roboto-Regular.ttf",
        Path("/usr/share/fonts/truetype/Open_Sans/static/OpenSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ],
    "medium": [
        BASE_DIR / "fonts" / "Roboto-Medium.ttf",
        Path("/usr/share/fonts/truetype/Open_Sans/static/OpenSans-SemiBold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf"),
    ],
    "bold": [
        BASE_DIR / "fonts" / "Roboto-Bold.ttf",
        Path("/usr/share/fonts/truetype/Open_Sans/static/OpenSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf"),
    ],
    "dollar": [
        Path("C:/Windows/Fonts/verdana.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        BASE_DIR / "fonts" / "Roboto-Regular.ttf",
        Path("/usr/share/fonts/truetype/Open_Sans/static/OpenSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ],
}

_FONT_FILE_CACHE: dict[str, Path | None] = {}
_rapid_ocr_engine: Any | None = None
AmountData = dict[str, str]
UserData = MutableMapping[str, Any]


@dataclass(frozen=True)
class VariantConfig:
    code: str
    template_name: str
    amount_separator: str
    recipient_limit: int
    title_case_recipient: bool
    name_crop: tuple[float, float, float, float]
    account_crop: tuple[float, float, float, float]
    time_position: tuple[int, int]
    amount_top: int
    recipient_top: int
    date_top: int
    sender_top: int
    row_y: tuple[int, int, int, int]

    @property
    def template_path(self) -> Path:
        return BASE_DIR / self.template_name


VARIANT_CONFIGS = {
    "deuna": VariantConfig(
        code="deuna",
        template_name="template_Deuna.png",
        amount_separator=",",
        recipient_limit=20,
        title_case_recipient=True,
        name_crop=(0.08, 0.46, 0.92, 0.53),
        account_crop=(0.24, 0.51, 0.74, 0.56),
        time_position=(34, 16),
        amount_top=354,
        recipient_top=436,
        date_top=484,
        sender_top=535,
        row_y=(618, 658, 698, 738),
    ),
    "nuevo_contacto": VariantConfig(
        code="nuevo_contacto",
        template_name="template_NuevoContacto.png",
        amount_separator=".",
        recipient_limit=28,
        title_case_recipient=False,
        name_crop=(0.06, 0.39, 0.73, 0.47),
        account_crop=(0.04, 0.28, 0.92, 0.34),
        time_position=(34, 18),
        amount_top=362,
        recipient_top=445,
        date_top=490,
        sender_top=538,
        row_y=(624, 664, 704, 744),
    ),
}


class ProcessingError(RuntimeError):
    pass


def get_user_data(context: ContextTypes.DEFAULT_TYPE) -> UserData:
    return cast(UserData, context.user_data)


def build_main_menu() -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("Start", callback_data="start")],
        [InlineKeyboardButton("Nombre de origen", callback_data="nombre_origen")],
        [InlineKeyboardButton("Cuenta origen", callback_data="cuenta_origen")],
    ]
    return InlineKeyboardMarkup(keyboard)


def collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_for_lookup(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", without_accents.lower())


def parse_amount(text: str) -> AmountData | None:
    match = re.fullmatch(r"\$\s*(\d+)([.,])(\d{2})", collapse_spaces(text))
    if not match:
        return None
    return {
        "whole": str(int(match.group(1))),
        "cents": match.group(3),
    }


def format_amount(amount_data: AmountData, separator: str) -> str:
    return f"$ {amount_data['whole']}{separator}{amount_data['cents']}"


def format_spanish_date(current_time: datetime) -> str:
    return f"El {current_time.day} de {MONTHS_ES[current_time.month]} de {current_time.year}"


def format_status_time(current_time: datetime) -> str:
    return f"{current_time.hour}:{current_time.minute:02d}"


def format_origin_account(account_number: str) -> str:
    digits = sanitize_account_number(account_number)
    return f"{digits[:3]} {digits[3:6]} {digits[6:]}"


def format_destination_account(last_digits: str) -> str:
    return f"*** *** {last_digits}"


def generate_comprobante_number() -> str:
    return "1" + "".join(random.choices("0123456789", k=8))


def resolve_font_path(font_role: str) -> Path | None:
    if font_role not in _FONT_FILE_CACHE:
        resolved = next((path for path in FONT_PATHS[font_role] if path.exists()), None)
        _FONT_FILE_CACHE[font_role] = resolved
    return _FONT_FILE_CACHE[font_role]


def load_font(font_role: str, size: int) -> Any:
    font_path = resolve_font_path(font_role)
    if font_path is None:
        return ImageFont.load_default()
    return ImageFont.truetype(str(font_path), size)


def measure_text(draw: ImageDraw.ImageDraw, text: str, font: Any) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return int(right - left)


def fit_font(
    draw: ImageDraw.ImageDraw,
    font_role: str,
    initial_size: int,
    text: str,
    max_width: int,
    min_size: int,
) -> Any:
    current_size = initial_size
    while current_size >= min_size:
        font = load_font(font_role, current_size)
        if measure_text(draw, text, font) <= max_width:
            return font
        current_size -= 1
    return load_font(font_role, min_size)


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    center_x: int,
    top_y: int,
    font: Any,
    fill: tuple[int, int, int],
) -> None:
    text_width = measure_text(draw, text, font)
    draw.text((center_x - int(text_width / 2), top_y), text, font=font, fill=fill)


def draw_right_aligned_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    right_x: int,
    top_y: int,
    font: Any,
    fill: tuple[int, int, int],
) -> None:
    text_width = measure_text(draw, text, font)
    draw.text((right_x - int(text_width), top_y), text, font=font, fill=fill)


def draw_centered_amount(
    draw: ImageDraw.ImageDraw,
    amount_text: str,
    center_x: int,
    top_y: int,
    dollar_font: Any,
    number_font: Any,
    fill: tuple[int, int, int],
) -> None:
    number_text = amount_text.replace("$", "", 1).strip()
    dollar_width = measure_text(draw, "$", dollar_font)
    number_width = measure_text(draw, number_text, number_font)
    gap = 8
    total_width = dollar_width + gap + number_width
    start_x = center_x - int(total_width / 2)

    draw.text((start_x, top_y - 1), "$", font=dollar_font, fill=fill)
    draw.text((start_x + dollar_width + gap, top_y), number_text, font=number_font, fill=fill)


def apply_joke_watermark(image: Image.Image) -> Image.Image:
    if not ENABLE_JOKE_WATERMARK:
        return image

    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    watermark_font = load_font("bold", 44)
    watermark_width = measure_text(overlay_draw, JOKE_WATERMARK_TEXT, watermark_font)
    start_x = int((image.width - watermark_width) / 2)
    start_y = int(image.height / 2) - 24

    overlay_draw.text(
        (start_x, start_y),
        JOKE_WATERMARK_TEXT,
        font=watermark_font,
        fill=(220, 32, 32, 92),
    )

    rotated_overlay = overlay.rotate(24, resample=RESAMPLING_BICUBIC, expand=False)
    return Image.alpha_composite(image.convert("RGBA"), rotated_overlay)


def truncate_text(text: str, limit: int) -> str:
    cleaned = collapse_spaces(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def smart_title_token(token: str) -> str:
    parts = re.split(r"([&./-])", token)
    converted_parts = []
    for part in parts:
        if not part or re.fullmatch(r"[&./-]", part):
            converted_parts.append(part)
        else:
            converted_parts.append(part[:1].upper() + part[1:].lower())
    return "".join(converted_parts)


def smart_title_case(text: str) -> str:
    return " ".join(smart_title_token(token) for token in collapse_spaces(text).split(" "))


def fix_common_ocr_issues(text: str) -> str:
    fixed = text.replace("|", "I")
    fixed = re.sub(r"([A-Za-z])lvan\b", r"\1 Ivan", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"\b[lI]van\b", "Ivan", fixed, flags=re.IGNORECASE)
    return collapse_spaces(fixed).strip(" .,:;-")


def preprocess_for_ocr(image: Image.Image, scale: float) -> Image.Image:
    prepared = ImageOps.exif_transpose(image).convert("L")
    prepared = ImageOps.autocontrast(prepared)
    if scale != 1:
        new_size = (
            max(1, int(prepared.width * scale)),
            max(1, int(prepared.height * scale)),
        )
        prepared = cast(Image.Image, prepared.resize(new_size, RESAMPLING_LANCZOS))
    return prepared


def get_rapid_ocr_engine() -> Any | None:
    global _rapid_ocr_engine
    if RapidOCR is None:
        return None
    if _rapid_ocr_engine is None:
        _rapid_ocr_engine = RapidOCR()
    return _rapid_ocr_engine


def ocr_text(image: Image.Image, scale: float = 2.0, tesseract_config: str = "--psm 6") -> str:
    prepared = preprocess_for_ocr(image, scale)

    if pytesseract is not None:
        for kwargs in (
            {"lang": "spa", "config": tesseract_config},
            {"config": tesseract_config},
        ):
            try:
                text = cast(str, pytesseract.image_to_string(prepared, **kwargs))
            except Exception:
                continue
            if text and text.strip():
                return text

    rapid_ocr_engine = get_rapid_ocr_engine()
    if rapid_ocr_engine is not None and np is not None:
        result, _ = rapid_ocr_engine(np.array(prepared))
        if result:
            return "\n".join(str(item[1]) for item in result)

    raise ProcessingError("No hay un motor OCR disponible en el servidor.")


def crop_by_ratio(image: Image.Image, ratios: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    left = int(width * ratios[0])
    top = int(height * ratios[1])
    right = int(width * ratios[2])
    bottom = int(height * ratios[3])
    return image.crop((left, top, right, bottom))


def detect_variant(full_text: str) -> str:
    normalized = normalize_for_lookup(full_text)
    if any(keyword in normalized for keyword in ("pagarcondeuna", "beneficiario", "vasatransferir")):
        return "deuna"
    if any(keyword in normalized for keyword in ("nuevocontacto", "nrodecuenta", "validarcuenta")):
        return "nuevo_contacto"
    raise ProcessingError(
        "No pude reconocer el formato del screenshot. Envia una captura de 'Pagar con Deuna' o 'Nuevo contacto'."
    )


def extract_name_from_lines(lines: list[str], label_markers: tuple[str, ...]) -> str:
    collected: list[str] = []
    label_found = False

    for line in lines:
        compact_line = normalize_for_lookup(line)
        if not label_found and any(marker in compact_line for marker in label_markers):
            label_found = True
            if ":" in line:
                tail = line.split(":", 1)[1].strip()
                if tail:
                    collected.append(tail)
            continue

        if label_found:
            if re.search(r"\d{4,}", line):
                break
            if any(
                stop_marker in compact_line
                for stop_marker in (
                    "cuenta",
                    "banco",
                    "correo",
                    "informacionpersonal",
                    "guardacontacto",
                    "validarcuenta",
                )
            ):
                break
            collected.append(line.strip())

    if collected:
        return collapse_spaces(" ".join(collected))
    return lines[-1] if lines else ""


def extract_last_four_digits(text: str) -> str:
    digits = re.findall(r"\d", text or "")
    if len(digits) < 4:
        raise ProcessingError("No pude extraer los ultimos 4 digitos de la cuenta destino.")
    return "".join(digits[-4:])


def extract_variant_payload(image: Image.Image, config: VariantConfig) -> tuple[str, str, str, str]:
    name_crop = crop_by_ratio(image, config.name_crop)
    account_crop = crop_by_ratio(image, config.account_crop)

    name_text = ocr_text(name_crop, scale=3.0)
    account_text = ocr_text(account_crop, scale=3.0)

    name_lines = [collapse_spaces(line) for line in name_text.splitlines() if collapse_spaces(line)]
    if config.code == "deuna":
        name = extract_name_from_lines(name_lines, ("beneficiario",))
        name = smart_title_case(fix_common_ocr_issues(name))
    else:
        name = extract_name_from_lines(
            name_lines,
            (
                "estacuentapertenecea",
                "cuentapertenece",
                "pertenecea",
            ),
        )
        name = fix_common_ocr_issues(name)

    if not name:
        raise ProcessingError("No pude extraer el nombre del destinatario del screenshot.")

    account_last_four = extract_last_four_digits(account_text)
    return name, account_last_four, name_text, account_text


def save_debug_text(output_path: Path, sections: dict[str, str]) -> None:
    debug_path = output_path.with_suffix(".txt")
    content: list[str] = []
    for key, value in sections.items():
        content.append(f"[{key}]")
        content.append(value.strip() if value else "")
        content.append("")
    debug_path.write_text("\n".join(content), encoding="utf-8")


def render_receipt(
    config: VariantConfig,
    amount_data: AmountData,
    nombre_origen: str,
    cuenta_origen: str,
    nombre_destino: str,
    account_last_four: str,
    created_at: datetime,
    output_path: Path,
) -> None:
    if not config.template_path.exists():
        raise ProcessingError(f"No existe la plantilla {config.template_name}.")

    with Image.open(config.template_path) as template_image:
        image = ImageOps.exif_transpose(template_image).convert("RGBA")

    draw = ImageDraw.Draw(image)

    amount_text = format_amount(amount_data, config.amount_separator)
    recipient_text = f"A {truncate_text(nombre_destino, config.recipient_limit)}"
    sender_text = f"De {collapse_spaces(nombre_origen)}"
    date_text = format_spanish_date(created_at)
    time_text = format_status_time(created_at)
    account_destino_text = format_destination_account(account_last_four)
    account_origen_text = format_origin_account(cuenta_origen)
    comprobante_text = generate_comprobante_number()

    time_font = fit_font(draw, "medium", 27, time_text, 100, 20)
    amount_font = fit_font(draw, "medium", 58, amount_text, 280, 44)
    amount_number_text = amount_text.replace("$", "", 1).strip()
    dollar_font = fit_font(draw, "dollar", 62, "$", 70, 42)
    amount_number_font = fit_font(draw, "medium", 58, amount_number_text, 240, 44)
    recipient_font = fit_font(draw, "medium", 25, recipient_text, 470, 20)
    date_font = fit_font(draw, "regular", 19, date_text, 320, 16)
    sender_font = fit_font(draw, "regular", 19, sender_text, 470, 16)
    row_label_font = load_font("regular", 18)
    draw.text(config.time_position, time_text, font=time_font, fill=PRIMARY_COLOR)
    draw_centered_amount(
        draw,
        amount_text,
        CENTER_X,
        config.amount_top,
        dollar_font,
        amount_number_font,
        PRIMARY_COLOR,
    )
    draw_centered_text(draw, recipient_text, CENTER_X, config.recipient_top, recipient_font, PRIMARY_COLOR)
    draw_centered_text(draw, date_text, CENTER_X, config.date_top, date_font, SECONDARY_COLOR)
    draw_centered_text(draw, sender_text, CENTER_X, config.sender_top, sender_font, SECONDARY_COLOR)

    rows = (
        ("Cuenta destino", account_destino_text),
        ("Banco destino", "Banco Pichincha"),
        ("Cuenta origen", account_origen_text),
        ("N° de comprobante", comprobante_text),
    )

    for row_y, (label, value) in zip(config.row_y, rows):
        draw.text((LEFT_X, row_y), label, font=row_label_font, fill=SECONDARY_COLOR)
        fitted_value_font = fit_font(draw, "regular", 18, value, 240, 16)
        draw_right_aligned_text(
            draw,
            value,
            RIGHT_X,
            row_y,
            fitted_value_font,
            SECONDARY_COLOR,
        )

    image = apply_joke_watermark(image)
    image.save(output_path)


def process_screenshot(
    screenshot_path: Path,
    amount_data: AmountData,
    nombre_origen: str,
    cuenta_origen: str,
    user_id: int,
) -> Path:
    created_at = datetime.now()

    with Image.open(screenshot_path) as screenshot_image:
        screenshot = ImageOps.exif_transpose(screenshot_image).convert("RGB")
        full_text = ocr_text(screenshot, scale=1.7, tesseract_config="--psm 11")
        variant_code = detect_variant(full_text)
        config = VARIANT_CONFIGS[variant_code]
        nombre_destino, account_last_four, name_text, account_text = extract_variant_payload(
            screenshot, config
        )

    output_path = OUTPUT_DIR / f"result_{variant_code}_{user_id}_{int(created_at.timestamp())}.png"
    render_receipt(
        config=config,
        amount_data=amount_data,
        nombre_origen=nombre_origen,
        cuenta_origen=cuenta_origen,
        nombre_destino=nombre_destino,
        account_last_four=account_last_four,
        created_at=created_at,
        output_path=output_path,
    )

    save_debug_text(
        output_path,
        {
            "variant": variant_code,
            "full_text": full_text,
            "name_text": name_text,
            "account_text": account_text,
            "nombre_destino": nombre_destino,
            "account_last_four": account_last_four,
        },
    )
    return output_path


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = cast(Message | None, update.message)
    if message is None:
        return
    user_data = get_user_data(context)
    user_data.pop("awaiting_field", None)
    await message.reply_text(
        "Bienvenido! Por favor, ingrese el monto en formato: $ 123.45 o $ 123,45",
        reply_markup=build_main_menu(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    message = cast(Message | None, query.message)
    if message is None:
        return

    await query.answer()
    user_data = get_user_data(context)
    action = query.data or ""

    if action == "start":
        user_data.pop("awaiting_field", None)
        await message.reply_text(
            "Bienvenido! Por favor, ingrese el monto en formato: $ 123.45 o $ 123,45"
        )
        return

    if action == "nombre_origen":
        user_data["awaiting_field"] = "nombre_origen"
        await message.reply_text(
            "Ingrese apellidos y nombres de origen.\nEjemplo: Lema Gavilanes Martha Alexandra"
        )
        return

    if action == "cuenta_origen":
        user_data["awaiting_field"] = "cuenta_origen"
        await message.reply_text(
            "Ingrese la cuenta de origen con 10 digitos.\nEjemplo: 2207031220"
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = cast(Message | None, update.message)
    if message is None:
        return

    text = collapse_spaces(message.text or "")
    user_data = get_user_data(context)
    awaiting_field = user_data.get("awaiting_field")

    if awaiting_field == "nombre_origen":
        if not text:
            await message.reply_text("El nombre de origen no puede estar vacio.")
            return
        user_data["nombre_origen"] = text
        user_data.pop("awaiting_field", None)
        await message.reply_text(
            f"Nombre de origen actualizado a: {text}",
            reply_markup=build_main_menu(),
        )
        return

    if awaiting_field == "cuenta_origen":
        account_digits = re.sub(r"\D", "", text)
        if len(account_digits) != 10:
            await message.reply_text("La cuenta de origen debe tener exactamente 10 digitos.")
            return
        user_data["cuenta_origen"] = account_digits
        user_data.pop("awaiting_field", None)
        await message.reply_text(
            f"Cuenta de origen actualizada a: {format_origin_account(account_digits)}",
            reply_markup=build_main_menu(),
        )
        return

    amount_data = parse_amount(text)
    if amount_data is None:
        await message.reply_text(
            "Por favor, ingrese el monto en el formato correcto: $ 123.45 o $ 123,45"
        )
        return

    user_data["monto"] = amount_data
    await message.reply_text("Ahora, enviame el screenshot con el nombre.")


async def download_image(update: Update) -> tuple[Path, int]:
    message = cast(Message | None, update.message)
    if message is None or update.effective_user is None:
        raise ProcessingError("No pude recibir la imagen.")

    user_id = update.effective_user.id
    timestamp = int(datetime.now().timestamp())

    if message.photo:
        telegram_file = await message.photo[-1].get_file()
        suffix = ".jpg"
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        telegram_file = await message.document.get_file()
        suffix = Path(message.document.file_name or ".jpg").suffix or ".jpg"
    else:
        raise ProcessingError("Envia una imagen valida.")

    screenshot_path = OUTPUT_DIR / f"screenshot_{user_id}_{timestamp}{suffix}"
    await telegram_file.download_to_drive(str(screenshot_path))
    return screenshot_path, user_id


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = cast(Message | None, update.message)
    if message is None:
        return

    user_data = get_user_data(context)
    if "monto" not in user_data:
        await message.reply_text(
            "Primero, ingrese el monto en formato: $ 123.45 o $ 123,45",
            reply_markup=build_main_menu(),
        )
        return

    try:
        screenshot_path, user_id = await download_image(update)
        result_path = await asyncio.to_thread(
            process_screenshot,
            screenshot_path,
            cast(AmountData, user_data["monto"]),
            cast(str, user_data.get("nombre_origen", DEFAULT_NOMBRE_ORIGEN)),
            cast(str, user_data.get("cuenta_origen", DEFAULT_CUENTA_ORIGEN)),
            user_id,
        )
    except ProcessingError as error:
        await message.reply_text(str(error))
        return
    except Exception as error:
        await message.reply_text(f"Error al procesar la imagen: {error}")
        return

    await message.reply_text("¡Tu imagen está lista!")
    chat_id = update.effective_chat.id if update.effective_chat is not None else user_id
    with result_path.open("rb") as image_file:
        await context.bot.send_photo(chat_id=chat_id, photo=image_file)


def main() -> None:
    application = Application.builder().token(TOKEN).build()

    image_filter = filters.PHOTO | filters.Document.IMAGE

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(image_filter, handle_screenshot))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.run_polling()


if __name__ == "__main__":
    main()
