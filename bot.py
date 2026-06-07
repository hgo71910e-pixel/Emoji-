#!/usr/bin/env python3
import asyncio
import copy
import gzip
import html
import io
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import numpy as np
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputSticker
from dotenv import load_dotenv
from matplotlib.font_manager import FontProperties
from matplotlib.path import Path as MPath
from matplotlib.textpath import TextPath

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("premium_emoji_bot")

BOT_TOKEN = os.getenv("PREMIUM_EMOJI_BOT_TOKEN", os.getenv("BOT_TOKEN", ""))
TEMPLATE_PATH = Path(os.getenv(
    "PREMIUM_EMOJI_TEMPLATE",
    "template.json",
))
PACK_PREFIX = os.getenv("PREMIUM_EMOJI_PACK_PREFIX", "premium")
TEXT_LIMIT = int(os.getenv("PREMIUM_EMOJI_TEXT_LIMIT", "20"))
SUBTITLE_LIMIT = int(os.getenv("PREMIUM_EMOJI_SUBTITLE_LIMIT", "18"))
CANVAS = 512

FONT_TEXT = [
    "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Black.otf",
    "/home/ecronx/Загрузки/ofont.ru_Montserrat.ttf",
    "/home/ecronx/Загрузки/eme-v3/eme/fonts/Montserrat.ttf",
    os.getenv("PREMIUM_EMOJI_FONT", ""),
    "/usr/share/fonts/google-carlito-fonts/Carlito-Bold.ttf",
    "/usr/share/fonts/google-droid-sans-fonts/DroidSans-Bold.ttf",
    "/usr/share/fonts/adwaita-mono-fonts/AdwaitaMono-Bold.ttf",
]
FONT_EMOJI = "/usr/share/fonts/google-noto-emoji-fonts/NotoEmoji-Regular.ttf"
FONT_WEIGHT = 900


def pe(eid: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>'


def premium_emoji_html(eid: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{html.escape(eid)}">{html.escape(fallback)}</tg-emoji>'


E = {
    "bot": pe("6030400221232501136", "🤖"),
    "text": pe("5771851822897566479", "🔡"),
    "info": pe("6028435952299413210", "ℹ️"),
    "write": pe("5870753782874246579", "✍️"),
    "brush": pe("6050679691004612757", "🖌"),
    "ok": pe("5870633910337015697", "✅"),
    "star": pe("5433622396718322437", "⭐️"),
    "wait": pe("5345906554510012647", "🔄"),
    "err": pe("5870657884844462243", "❌"),
}

ICON = {
    "info": "6028435952299413210",
    "create": "5870753782874246579",
    "back": "5893057118545646106",
    "skip": "5870633910337015697",
    "brush": "6050679691004612757",
}

COLORS = [
    ("Фиолетовый", "#8B5CF6"),
    ("Синий", "#3B82F6"),
    ("Голубой", "#06B6D4"),
    ("Мятный", "#14B8A6"),
    ("Зеленый", "#22C55E"),
    ("Желтый", "#EAB308"),
    ("Оранжевый", "#F97316"),
    ("Красный", "#EF4444"),
    ("Розовый", "#EC4899"),
    ("Серый", "#94A3B8"),
    ("Черный", "#111827"),
    ("Белый", "#F8FAFC"),
]


class Flow(StatesGroup):
    main_text = State()
    subtitle = State()
    separate_text_color = State()
    main_color = State()
    subtitle_color = State()
    badge_color = State()


@dataclass
class UploadResult:
    pack_name: str
    custom_emoji_id: str | None


def button(text: str, callback_data: str, icon: str | None = None) -> InlineKeyboardButton:
    data = {"text": text, "callback_data": callback_data}
    if icon:
        data["icon_custom_emoji_id"] = icon
    return InlineKeyboardButton(**data)


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        button("О чем бот", "about", ICON["info"]),
        button("Создать", "create", ICON["create"]),
    ]])


def about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("Создать", "create", ICON["create"])],
        [button("Назад", "back_start", ICON["back"])],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button("Назад", "back_start", ICON["back"])]])


def skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button("Пропустить", "skip_subtitle", ICON["skip"])]])


def separate_color_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        button("Пропустить", "text_color_skip", ICON["skip"]),
        button("Да", "text_color_yes", ICON["brush"]),
    ]])


def color_keyboard(target: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for idx, (name, _) in enumerate(COLORS):
        row.append(button(name, f"color:{target}:{idx}", ICON["brush"]))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([button("Назад", "back_start", ICON["back"])])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def start_text() -> str:
    return (
        f"<blockquote>{E['bot']} Привет. Я создаю премиум-эмодзи из текста, буквы или короткого знака.</blockquote>\n\n"
        f"{E['text']} Нажмите кнопку создания, отправьте текст и выберите цвет."
    )


def about_text() -> str:
    return (
        f"<blockquote>{E['info']} Бот создает премиум-эмодзи из вашего текста, буквы или короткого логотипа.</blockquote>\n\n"
        "После генерации результат придет прямо как премиум-эмодзи в сообщении."
    )


def ask_main_text() -> str:
    return (
        f"<blockquote>{E['write']} Отправьте текст для создания премиум-эмодзи.</blockquote>\n\n"
        "Подойдет буква, слово, короткая фраза или название логотипа."
    )


def display_value(value: str, html_display: str | None = None) -> str:
    return html_display or html.escape(value)


def format_context(
    main_text: str,
    subtitle: str | None = "",
    main_display: str | None = None,
    subtitle_display: str | None = None,
) -> str:
    lines = [f"Основной текст: <b>{display_value(main_text, main_display)}</b>"]
    if subtitle:
        lines.append(f"Подзаголовок: <b>{display_value(subtitle, subtitle_display)}</b>")
    return "\n".join(lines)


def ask_subtitle_text(main_text: str, main_display: str | None = None) -> str:
    return f"<blockquote>{E['text']} Хочешь что то добавить снизу?</blockquote>\n\n{format_context(main_text, main_display=main_display)}"


def ask_separate_color_text(main_text: str, subtitle: str | None, main_display: str | None = None, subtitle_display: str | None = None) -> str:
    return f"<blockquote>{E['brush']} Делать ли текст отдельного цвета?</blockquote>\n\n{format_context(main_text, subtitle, main_display, subtitle_display)}"


def ask_main_color_text(main_text: str, subtitle: str | None, main_display: str | None = None, subtitle_display: str | None = None) -> str:
    return f"<blockquote>{E['brush']} Выбери цвет для основного текста.</blockquote>\n\n{format_context(main_text, subtitle, main_display, subtitle_display)}"


def ask_subtitle_color_text(main_text: str, subtitle: str | None, main_display: str | None = None, subtitle_display: str | None = None) -> str:
    return f"<blockquote>{E['brush']} Выбери цвет для подзаголовка.</blockquote>\n\n{format_context(main_text, subtitle, main_display, subtitle_display)}"


def ask_badge_color_text(main_text: str, subtitle: str | None, main_display: str | None = None, subtitle_display: str | None = None) -> str:
    caption = "Текст"
    lines = [f"{caption}: <b>{display_value(main_text, main_display)}</b>"]
    if subtitle:
        lines.append(f"Подзаголовок: <b>{display_value(subtitle, subtitle_display)}</b>")
    return f"<blockquote>{E['brush']} Выберите цвет для премиум-эмодзи.</blockquote>\n\n" + "\n".join(lines)


def extract_message_text_and_display(message: types.Message) -> tuple[str, str | None]:
    text, display, _ = extract_message_text_display_and_custom_id(message)
    return text, display


def extract_message_text_display_and_custom_id(message: types.Message) -> tuple[str, str | None, str | None]:
    text = (message.text or "").strip()
    for entity in message.entities or []:
        if entity.type == "custom_emoji" and entity.custom_emoji_id:
            try:
                fallback = entity.extract_from(message.text or "").strip()
            except Exception:
                fallback = text
            if not fallback:
                fallback = text
            return fallback, premium_emoji_html(entity.custom_emoji_id, fallback), entity.custom_emoji_id
    return text, None, None


async def download_custom_emoji_lottie(bot_obj: Bot, custom_emoji_id: str) -> dict:
    stickers = await bot_obj.get_custom_emoji_stickers([custom_emoji_id])
    if not stickers:
        raise ValueError("Не удалось получить премиум-эмодзи")
    sticker = stickers[0]
    if not getattr(sticker, "is_animated", False):
        raise ValueError("Этот премиум-эмодзи не является TGS-анимацией")
    downloaded = await bot_obj.download(getattr(sticker, "file_id", ""))
    if downloaded is None:
        raise ValueError("Не удалось скачать премиум-эмодзи")
    payload = downloaded.read() if hasattr(downloaded, "read") else downloaded
    if not isinstance(payload, bytes):
        payload = bytes(payload)
    try:
        return json.loads(gzip.decompress(payload).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Не удалось прочитать TGS-анимацию премиум-эмодзи") from exc


def _hex_to_lottie(value: str) -> list[float]:
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [1.0]


def find_group_by_name(obj, name: str):
    if isinstance(obj, dict):
        if obj.get("nm") == name:
            return obj
        for value in obj.values():
            found = find_group_by_name(value, name)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_group_by_name(item, name)
            if found is not None:
                return found
    return None


def find_shape_group_by_name(obj, name: str):
    if isinstance(obj, dict):
        if obj.get("ty") == "gr" and obj.get("nm") == name:
            return obj
        for value in obj.values():
            found = find_shape_group_by_name(value, name)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_shape_group_by_name(item, name)
            if found is not None:
                return found
    return None


def _pick_font(text: str) -> str | None:
    has_emoji = any(unicodedata.category(ch) in ("So", "Cs") for ch in text)
    paths = ([FONT_EMOJI] if has_emoji else []) + FONT_TEXT
    return next((path for path in paths if path and os.path.exists(path)), None)


def _reverse_shape(shape: dict) -> dict:
    k = shape["ks"]["k"]
    vertices, in_tangents, out_tangents = k["v"], k["i"], k["o"]
    count = len(vertices)
    new_vertices = list(reversed(vertices))
    new_out = [[-in_tangents[count - 1 - idx][0], -in_tangents[count - 1 - idx][1]] for idx in range(count)]
    new_in = [[-out_tangents[count - 1 - idx][0], -out_tangents[count - 1 - idx][1]] for idx in range(count)]
    return {"ty": "sh", "d": 1, "ks": {"a": 0, "k": {"v": new_vertices, "i": new_in, "o": new_out, "c": True}}}


def _mpath_to_shapes(vertices: np.ndarray, codes: np.ndarray, tx: float, ty: float, scale: float) -> list[dict]:
    shapes = []
    idx = 0
    total = len(codes)
    while idx < total:
        if codes[idx] != MPath.MOVETO:
            idx += 1
            continue
        sv, si, so = [], [], []

        def transform(x, y):
            return tx + x * scale, ty - y * scale

        def add_vertex(x, y, in_x=0.0, in_y=0.0, out_x=0.0, out_y=0.0):
            lx, ly = transform(x, y)
            sv.append([round(lx, 3), round(ly, 3)])
            si.append([round(in_x, 3), round(in_y, 3)])
            so.append([round(out_x, 3), round(out_y, 3)])

        px, py = vertices[idx]
        add_vertex(px, py)
        idx += 1
        while idx < total and codes[idx] != MPath.MOVETO:
            code = codes[idx]
            if code == MPath.LINETO:
                nx, ny = vertices[idx]
                add_vertex(nx, ny)
                idx += 1
            elif code == MPath.CURVE3:
                cpx, cpy = vertices[idx]
                ex, ey = vertices[idx + 1]
                lcp = transform(cpx, cpy)
                le = transform(ex, ey)
                lp = sv[-1]
                so[-1] = [round((lcp[0] - lp[0]) * 2 / 3, 3), round((lcp[1] - lp[1]) * 2 / 3, 3)]
                add_vertex(ex, ey, round((lcp[0] - le[0]) * 2 / 3, 3), round((lcp[1] - le[1]) * 2 / 3, 3))
                idx += 2
            elif code == MPath.CURVE4:
                c1x, c1y = vertices[idx]
                c2x, c2y = vertices[idx + 1]
                ex, ey = vertices[idx + 2]
                lc1 = transform(c1x, c1y)
                lc2 = transform(c2x, c2y)
                le = transform(ex, ey)
                lp = sv[-1]
                so[-1] = [round(lc1[0] - lp[0], 3), round(lc1[1] - lp[1], 3)]
                add_vertex(ex, ey, round(lc2[0] - le[0], 3), round(lc2[1] - le[1], 3))
                idx += 3
            elif code == MPath.CLOSEPOLY:
                idx += 1
                break
            else:
                idx += 1
        if len(sv) >= 2:
            shapes.append({"ty": "sh", "d": 1, "ks": {"a": 0, "k": {"v": sv, "i": si, "o": so, "c": True}}})
    return shapes


def text_to_lottie_shapes(text: str, center_y: float, max_width: float, max_height: float) -> list[dict]:
    font_path = _pick_font(text)
    if not font_path:
        raise ValueError("Не найден подходящий шрифт")
    text_path = TextPath((0, 0), text, size=100, prop=FontProperties(fname=font_path, weight=FONT_WEIGHT))
    vertices = text_path.vertices
    if len(vertices) == 0:
        return []
    raw_width = vertices[:, 0].max() - vertices[:, 0].min()
    raw_height = vertices[:, 1].max() - vertices[:, 1].min()
    if raw_width == 0 or raw_height == 0:
        return []
    scale = min(max_width / raw_width, max_height / raw_height)
    scaled_width = raw_width * scale
    scaled_height = raw_height * scale
    raw_x_min = vertices[:, 0].min()
    raw_y_min = vertices[:, 1].min()
    tx = CANVAS / 2 - scaled_width / 2 - raw_x_min * scale
    ty = center_y + scaled_height / 2 + raw_y_min * scale
    return [_reverse_shape(shape) for shape in _mpath_to_shapes(vertices, text_path.codes, tx, ty, scale)]


def _make_fill(color_hex: str) -> dict:
    return {"ty": "fl", "c": {"a": 0, "k": _hex_to_lottie(color_hex)}, "o": {"a": 0, "k": 100}, "r": 1}


def _make_transform() -> dict:
    return {
        "ty": "tr",
        "a": {"a": 0, "k": [0, 0]},
        "p": {"a": 0, "k": [0, 0]},
        "s": {"a": 0, "k": [100, 100]},
        "r": {"a": 0, "k": 0},
        "o": {"a": 0, "k": 100},
        "sk": {"a": 0, "k": 0},
        "sa": {"a": 0, "k": 0},
    }


def _replace_group_text(data: dict, group_name: str, text: str, color_hex: str, center_y: float, max_height: float) -> None:
    group = find_shape_group_by_name(data, group_name)
    if group is None:
        raise ValueError(f"Группа {group_name} не найдена")
    if text:
        shapes = text_to_lottie_shapes(text, center_y=center_y, max_width=360, max_height=max_height)
        group["it"] = shapes + [_make_fill(color_hex), _make_transform()]
    else:
        group["it"] = [_make_transform()]


def _walk_replace_ref_ids(obj, mapping: dict[str, str]) -> None:
    if isinstance(obj, dict):
        if obj.get("refId") in mapping:
            obj["refId"] = mapping[obj["refId"]]
        for value in obj.values():
            _walk_replace_ref_ids(value, mapping)
    elif isinstance(obj, list):
        for item in obj:
            _walk_replace_ref_ids(item, mapping)


def _prefix_source_assets(source: dict, prefix: str) -> dict:
    source = copy.deepcopy(source)
    mapping = {}
    for asset in source.get("assets", []) or []:
        asset_id = asset.get("id")
        if asset_id:
            mapping[asset_id] = f"{prefix}_{asset_id}"
            asset["id"] = mapping[asset_id]
    if mapping:
        _walk_replace_ref_ids(source.get("layers", []), mapping)
        _walk_replace_ref_ids(source.get("assets", []), mapping)
    return source


def _clear_shape_group(data: dict, group_name: str) -> None:
    group = find_shape_group_by_name(data, group_name)
    if group is not None:
        group["it"] = [_make_transform()]


def _embed_main_premium_emoji(data: dict, emoji_lottie: dict, center_y: float, max_size: float) -> None:
    source = _prefix_source_assets(emoji_lottie, "main_premium_src")
    source_width = float(source.get("w") or CANVAS)
    source_height = float(source.get("h") or CANVAS)
    scale = min(max_size / source_width, max_size / source_height) * 100
    comp_op = float(data.get("op", source.get("op", 60) or 60))
    for layer in source.get("layers", []) or []:
        if isinstance(layer, dict):
            layer["op"] = max(float(layer.get("op", comp_op) or comp_op), comp_op)

    data.setdefault("assets", [])
    data["assets"] = [asset for asset in data["assets"] if asset.get("id") != "main_premium_emoji_asset"]
    data["assets"].extend(source.get("assets", []) or [])
    data["assets"].append({
        "id": "main_premium_emoji_asset",
        "w": int(source_width),
        "h": int(source_height),
        "layers": source.get("layers", []),
    })
    next_ind = max([int(layer.get("ind", 0) or 0) for layer in data.get("layers", [])] + [0]) + 1
    layer = {
        "ddd": 0,
        "ty": 0,
        "ind": next_ind,
        "nm": "main_premium_emoji",
        "refId": "main_premium_emoji_asset",
        "sr": 1,
        "ks": {
            "a": {"a": 0, "k": [source_width / 2, source_height / 2]},
            "p": {"a": 0, "k": [CANVAS / 2, center_y]},
            "s": {"a": 0, "k": [round(scale, 3), round(scale, 3)]},
            "r": {"a": 0, "k": 0},
            "o": {"a": 0, "k": 100},
            "sk": {"a": 0, "k": 0},
            "sa": {"a": 0, "k": 0},
        },
        "ao": 0,
        "w": int(source_width),
        "h": int(source_height),
        "ip": 0,
        "op": comp_op,
        "st": 0,
        "bm": 0,
    }
    data["layers"] = [existing for existing in data.get("layers", []) if existing.get("nm") != "main_premium_emoji"]
    data["layers"].insert(0, layer)


def _set_background_color(data: dict, color_hex: str) -> None:
    background = find_shape_group_by_name(data, "background")
    if background is None:
        raise ValueError("Группа background не найдена")
    for item in background.get("it", []):
        if isinstance(item, dict) and item.get("ty") == "fl":
            item.setdefault("c", {})["k"] = _hex_to_lottie(color_hex)


def _trim_template(data: dict) -> dict:
    data = copy.deepcopy(data)
    data["op"] = min(float(data.get("op", 60)), 180.0)
    for layer in data.get("layers", []):
        if isinstance(layer, dict):
            layer["op"] = data["op"]
    return data


def build_lottie(
    main_text: str,
    subtitle: str | None,
    main_text_color: str,
    subtitle_color: str,
    background_color: str,
    main_emoji_lottie: dict | None = None,
) -> dict:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as file:
        data = json.load(file)
    data = _trim_template(data)
    has_subtitle = bool(subtitle)
    if main_emoji_lottie:
        _clear_shape_group(data, "text")
        _embed_main_premium_emoji(data, main_emoji_lottie, 230 if has_subtitle else 256, 170 if has_subtitle else 210)
    else:
        _replace_group_text(data, "text", main_text, main_text_color, 240 if has_subtitle else 266, 110 if has_subtitle else 145)
    _replace_group_text(data, "subtitle", subtitle or "", subtitle_color, 322, 60)
    _set_background_color(data, background_color)
    return data


def build_tgs(
    main_text: str,
    subtitle: str | None,
    main_text_color: str,
    subtitle_color: str,
    background_color: str,
    main_emoji_lottie: dict | None = None,
) -> bytes:
    data = build_lottie(main_text, subtitle, main_text_color, subtitle_color, background_color, main_emoji_lottie)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=9) as gz:
        gz.write(raw)
    payload = out.getvalue()
    if len(payload) > 64 * 1024:
        raise ValueError(f"TGS слишком большой: {len(payload) / 1024:.1f} KB")
    return payload


def pack_name_for(user_id: int, bot_username: str) -> str:
    safe_prefix = re.sub(r"[^a-z0-9_]", "", PACK_PREFIX.lower()) or "premium"
    return f"{safe_prefix}_{user_id}_by_{bot_username}"


async def upload_custom_emoji(bot_obj: Bot, user_id: int, tgs_payload: bytes) -> UploadResult:
    me = await bot_obj.get_me()
    pack_name = pack_name_for(user_id, me.username)
    sticker = InputSticker(
        sticker=BufferedInputFile(tgs_payload, filename="emoji.tgs"),
        emoji_list=["⭐"],
        format="animated",
    )
    try:
        await bot_obj.get_sticker_set(pack_name)
    except TelegramBadRequest:
        await bot_obj.create_new_sticker_set(
            user_id=user_id,
            name=pack_name,
            title="Premium Emoji",
            stickers=[sticker],
            sticker_type="custom_emoji",
        )
    else:
        await bot_obj.add_sticker_to_set(user_id=user_id, name=pack_name, sticker=sticker)

    custom_emoji_id = None
    try:
        sticker_set = await bot_obj.get_sticker_set(pack_name)
        stickers = getattr(sticker_set, "stickers", []) or []
        if stickers:
            custom_emoji_id = getattr(stickers[-1], "custom_emoji_id", None)
    except Exception:
        custom_emoji_id = None
    return UploadResult(pack_name=pack_name, custom_emoji_id=custom_emoji_id)


bot = Bot(token=BOT_TOKEN or "123:ABC", default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(start_text(), reply_markup=start_keyboard())


@dp.callback_query(F.data == "back_start")
async def cb_back_start(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(start_text(), reply_markup=start_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "about")
async def cb_about(callback: types.CallbackQuery):
    await callback.message.edit_text(about_text(), reply_markup=about_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "create")
async def cb_create(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Flow.main_text)
    await callback.message.edit_text(ask_main_text(), reply_markup=back_keyboard())
    await callback.answer()


@dp.message(Flow.main_text, F.text)
async def got_main_text(message: types.Message, state: FSMContext):
    text, main_display, main_custom_emoji_id = extract_message_text_display_and_custom_id(message)
    if not text or text.startswith("/"):
        return
    if len(text) > TEXT_LIMIT:
        await message.answer(f"{E['err']} Максимум {TEXT_LIMIT} символов.")
        return
    main_emoji_lottie = None
    if main_custom_emoji_id:
        try:
            main_emoji_lottie = await download_custom_emoji_lottie(message.bot, main_custom_emoji_id)
        except Exception as exc:
            await message.answer(f"{E['err']} <b>Не смог скачать премиум-эмодзи:</b> <code>{html.escape(str(exc))}</code>")
            return
    await state.update_data(
        main_text=text,
        main_display=main_display,
        main_custom_emoji_id=main_custom_emoji_id,
        main_emoji_lottie=main_emoji_lottie,
    )
    await state.set_state(Flow.subtitle)
    await message.answer(ask_subtitle_text(text, main_display), reply_markup=skip_keyboard())


@dp.message(Flow.subtitle, F.text)
async def got_subtitle(message: types.Message, state: FSMContext):
    subtitle, subtitle_display = extract_message_text_and_display(message)
    if len(subtitle) > SUBTITLE_LIMIT:
        await message.answer(f"{E['err']} Максимум {SUBTITLE_LIMIT} символов.")
        return
    data = await state.get_data()
    await state.update_data(subtitle=subtitle, subtitle_display=subtitle_display)
    await state.set_state(Flow.separate_text_color)
    await message.answer(
        ask_separate_color_text(data["main_text"], subtitle, data.get("main_display"), subtitle_display),
        reply_markup=separate_color_keyboard(),
    )


@dp.callback_query(F.data == "skip_subtitle")
async def cb_skip_subtitle(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(subtitle="", subtitle_display=None)
    await state.set_state(Flow.separate_text_color)
    await callback.message.edit_text(
        ask_separate_color_text(data["main_text"], "", data.get("main_display")),
        reply_markup=separate_color_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "text_color_skip")
async def cb_text_color_skip(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(main_text_color="#FFFFFF", subtitle_color="#FFFFFF")
    await state.set_state(Flow.badge_color)
    await callback.message.edit_text(
        ask_badge_color_text(data["main_text"], data.get("subtitle", ""), data.get("main_display"), data.get("subtitle_display")),
        reply_markup=color_keyboard("badge"),
    )
    await callback.answer()


@dp.callback_query(F.data == "text_color_yes")
async def cb_text_color_yes(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(Flow.main_color)
    await callback.message.edit_text(
        ask_main_color_text(data["main_text"], data.get("subtitle", ""), data.get("main_display"), data.get("subtitle_display")),
        reply_markup=color_keyboard("main"),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("color:"))
async def cb_color(callback: types.CallbackQuery, state: FSMContext):
    _, target, idx_raw = callback.data.split(":", 2)
    _, color = COLORS[int(idx_raw)]
    data = await state.get_data()

    if target == "main":
        await state.update_data(main_text_color=color)
        if data.get("subtitle"):
            await state.set_state(Flow.subtitle_color)
            await callback.message.edit_text(
                ask_subtitle_color_text(data["main_text"], data.get("subtitle", ""), data.get("main_display"), data.get("subtitle_display")),
                reply_markup=color_keyboard("subtitle"),
            )
        else:
            await state.update_data(subtitle_color=color)
            await state.set_state(Flow.badge_color)
            await callback.message.edit_text(
                ask_badge_color_text(data["main_text"], "", data.get("main_display")),
                reply_markup=color_keyboard("badge"),
            )
    elif target == "subtitle":
        await state.update_data(subtitle_color=color)
        await state.set_state(Flow.badge_color)
        await callback.message.edit_text(
            ask_badge_color_text(data["main_text"], data.get("subtitle", ""), data.get("main_display"), data.get("subtitle_display")),
            reply_markup=color_keyboard("badge"),
        )
    elif target == "badge":
        await state.update_data(background_color=color)
        await callback.answer()
        await generate_and_send(callback.message, state)
        return
    await callback.answer()


async def generate_and_send(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    status = await message.edit_text(f"{E['wait']} <b>Создаю премиум-эмодзи...</b>")
    try:
        tgs_payload = await asyncio.to_thread(
            build_tgs,
            data["main_text"],
            data.get("subtitle", ""),
            data.get("main_text_color", "#FFFFFF"),
            data.get("subtitle_color", "#FFFFFF"),
            data.get("background_color", "#8B5CF6"),
            data.get("main_emoji_lottie"),
        )
        result = await upload_custom_emoji(bot, message.chat.id, tgs_payload)
        if result.custom_emoji_id:
            rendered = f'<tg-emoji emoji-id="{result.custom_emoji_id}">⭐️</tg-emoji>'
        else:
            rendered = E["star"]
        final_text = (
            f"<blockquote>{E['ok']} Готово. Премиум-эмодзи создан.</blockquote>\n\n"
            f"{rendered}\n\n"
            f"Исходный текст: <b>{display_value(data['main_text'], data.get('main_display'))}</b>"
        )
        if data.get("subtitle"):
            final_text += f"\nПодзаголовок: <b>{display_value(data['subtitle'], data.get('subtitle_display'))}</b>"
        final_text += f'\n\n<a href="https://t.me/addemoji/{result.pack_name}">Открыть пак</a>'
        await status.edit_text(final_text, reply_markup=start_keyboard())
        if not result.custom_emoji_id:
            await message.answer_document(BufferedInputFile(tgs_payload, filename="emoji.tgs"))
    except Exception as exc:
        log.exception("generation failed")
        await status.edit_text(f"{E['err']} <b>Ошибка:</b> <code>{html.escape(str(exc))}</code>", reply_markup=start_keyboard())


@dp.message()
async def fallback(message: types.Message, state: FSMContext):
    if await state.get_state() is None:
        await cmd_start(message, state)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Задай PREMIUM_EMOJI_BOT_TOKEN в .env")
    if not TEMPLATE_PATH.exists():
        raise RuntimeError(f"Шаблон не найден: {TEMPLATE_PATH}")
    log.info("Premium Emoji Bot starting")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
