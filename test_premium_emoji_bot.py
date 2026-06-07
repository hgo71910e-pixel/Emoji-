import gzip
import io
import json
import os
import unittest

os.environ.setdefault("PREMIUM_EMOJI_BOT_TOKEN", "123:ABC")

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetStickerSet

import premium_emoji_bot as bot


class PremiumEmojiBotTests(unittest.TestCase):
    def test_context_text_omits_subtitle_when_missing(self):
        text = bot.format_context("ecronx", "")

        self.assertIn("Основной текст: <b>ecronx</b>", text)
        self.assertNotIn("Подзаголовок:", text)

    def test_context_text_uses_premium_emoji_markup_when_present(self):
        text = bot.format_context("💵", "", main_display=bot.premium_emoji_html("5395422644055086206", "💵"))

        self.assertIn('<tg-emoji emoji-id="5395422644055086206">💵</tg-emoji>', text)
        self.assertNotIn("Основной текст: <b>💵</b>", text)

    def test_context_text_includes_subtitle_when_present(self):
        text = bot.format_context("ecronx", "dev")

        self.assertIn("Основной текст: <b>ecronx</b>", text)
        self.assertIn("Подзаголовок: <b>dev</b>", text)

    def test_font_weight_is_900(self):
        self.assertEqual(900, bot.FONT_WEIGHT)

    def test_build_tgs_generates_valid_lottie_under_telegram_limit(self):
        tgs = bot.build_tgs(
            main_text="ecronx",
            subtitle="dev",
            main_text_color="#3B82F6",
            subtitle_color="#22C55E",
            background_color="#8B5CF6",
        )

        self.assertLess(len(tgs), 64 * 1024)
        data = json.loads(gzip.decompress(tgs).decode("utf-8"))
        self.assertEqual(1, data["tgs"])
        self.assertEqual(512, data["w"])
        self.assertEqual(512, data["h"])
        self.assertTrue(bot.find_group_by_name(data, "text"))
        self.assertTrue(bot.find_group_by_name(data, "subtitle"))

    def test_build_tgs_embeds_premium_emoji_lottie_instead_of_text_glyph(self):
        source = {
            "tgs": 1,
            "v": "5.5.2",
            "fr": 60,
            "ip": 0,
            "op": 60,
            "w": 512,
            "h": 512,
            "ddd": 0,
            "assets": [],
            "layers": [{"ddd": 0, "ty": 4, "ind": 1, "nm": "source premium", "ks": {}, "shapes": [], "ip": 0, "op": 60, "st": 0, "bm": 0}],
        }

        tgs = bot.build_tgs(
            main_text="💵",
            subtitle="dev",
            main_text_color="#3B82F6",
            subtitle_color="#22C55E",
            background_color="#8B5CF6",
            main_emoji_lottie=source,
        )

        data = json.loads(gzip.decompress(tgs).decode("utf-8"))
        self.assertTrue(any(asset.get("id") == "main_premium_emoji_asset" for asset in data["assets"]))
        self.assertEqual("main_premium_emoji", data["layers"][0]["nm"])
        self.assertEqual(0, data["layers"][0]["ty"])
        self.assertEqual(["tr"], [item["ty"] for item in bot.find_shape_group_by_name(data, "text")["it"]])

    def test_color_keyboard_has_expected_rows(self):
        kb = bot.color_keyboard("main")

        self.assertEqual(5, len(kb.inline_keyboard))
        self.assertEqual(3, len(kb.inline_keyboard[0]))
        self.assertEqual("Фиолетовый", kb.inline_keyboard[0][0].text)


class CustomEmojiIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_custom_emoji_lottie_reads_tgs_json(self):
        source = {"tgs": 1, "w": 512, "h": 512, "layers": []}
        payload = gzip.compress(json.dumps(source).encode("utf-8"))
        fake = FakeDownloadBot(payload)

        result = await bot.download_custom_emoji_lottie(fake, "5395422644055086206")

        self.assertEqual(source, result)
        self.assertEqual([["5395422644055086206"]], fake.custom_emoji_calls)
        self.assertEqual("emoji_file_id", fake.download_calls[0])

    async def test_upload_returns_custom_emoji_id_from_pack(self):
        fake = FakeBot()

        result = await bot.upload_custom_emoji(
            fake,
            user_id=12345,
            tgs_payload=b"payload",
        )

        self.assertEqual("premium_12345_by_testbot", result.pack_name)
        self.assertEqual("999000111222", result.custom_emoji_id)
        self.assertEqual(1, len(fake.create_calls))


class FakeMe:
    username = "testbot"


class FakeSticker:
    custom_emoji_id = "999000111222"
    file_unique_id = "new_unique"


class FakeStickerSet:
    stickers = [FakeSticker()]


class FakeDownloadedSticker:
    is_animated = True
    file_id = "emoji_file_id"


class FakeDownloadBot:
    def __init__(self, payload):
        self.payload = payload
        self.custom_emoji_calls = []
        self.download_calls = []

    async def get_custom_emoji_stickers(self, custom_emoji_ids):
        self.custom_emoji_calls.append(custom_emoji_ids)
        return [FakeDownloadedSticker()]

    async def download(self, file):
        self.download_calls.append(file)
        return io.BytesIO(self.payload)


class FakeBot:
    def __init__(self):
        self.get_sticker_set_calls = 0
        self.create_calls = []

    async def get_me(self):
        return FakeMe()

    async def create_new_sticker_set(self, **kwargs):
        self.create_calls.append(kwargs)
        return True

    async def get_sticker_set(self, name):
        self.get_sticker_set_calls += 1
        if self.get_sticker_set_calls == 1:
            raise TelegramBadRequest(
                method=GetStickerSet(name=name),
                message="Bad Request: STICKERSET_INVALID",
            )
        return FakeStickerSet()


if __name__ == "__main__":
    unittest.main()
