"""The plugin's own texts (src/kobracontrol/i18n.py): every text the code passes to tr()/lazy() has an entry in each
catalogue, with the same placeholders in the same order, and the language follows Settings, then OrcaSlicer."""
import ast
import glob
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "kobracontrol")
sys.path[:0] = [SRC]

import i18n  # noqa: E402

PLACEHOLDER = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[sdrfgx%]")


def marked_texts():
    """Every string literal passed to tr() or lazy() in the plugin's modules."""
    found = set()
    for path in glob.glob(os.path.join(SRC, "*.py")):
        if os.path.basename(path).startswith("lang_"):
            continue
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("tr", "lazy")
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found | set(i18n.STATES)


class CatalogueTests(unittest.TestCase):
    def test_every_marked_text_is_in_every_catalogue(self):
        texts = marked_texts()
        self.assertGreater(len(texts), 200)
        for lang, cat in i18n.CATALOGUES.items():
            with self.subTest(lang=lang):
                self.assertEqual(sorted(texts - set(cat)), [], "missing in %s" % lang)
                self.assertEqual(sorted(set(cat) - texts), [], "unused in %s" % lang)

    def test_same_placeholders_in_the_same_order(self):
        for lang, cat in i18n.CATALOGUES.items():
            for en, text in cat.items():
                self.assertEqual(PLACEHOLDER.findall(text), PLACEHOLDER.findall(en), "%s: %r" % (lang, en))

    def test_translated_not_copied(self):
        """A catalogue left in English would pass the checks above; only a few texts may stay as they are."""
        for lang, cat in i18n.CATALOGUES.items():
            same = [en for en, text in cat.items() if en == text]
            self.assertLessEqual(len(same), 5, "%s: %s" % (lang, same))

    def test_polish_is_complete(self):
        self.assertIn("pl", i18n.LANGUAGES)
        self.assertEqual(sorted(i18n.CATALOGUES["pl"]), sorted(marked_texts()))

    def test_chinese_uses_chinese_punctuation(self):
        for en, text in i18n.CATALOGUES["zh-CN"].items():
            if re.search(r"[一-鿿]", text):
                self.assertNotRegex(text, r"[一-鿿][,;?!]|[一-鿿]\.(\s|$)", en)


class LanguageTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_normalize(self):
        cases = {"pt_BR": "pt-BR", "pt": "pt-BR", "es_ES": "es", "es-419": "es", "de_DE": "de", "de": "de",
                 "zh_CN": "zh-CN", "zh_TW": "zh-CN", "zh-Hant": "zh-CN", "pl_PL": "pl", "pl": "pl", "PL-pl": "pl", "en_US": "en", "fr_FR": None, "": None, None: None}
        for code, want in cases.items():
            self.assertEqual(i18n.normalize(code), want, code)

    def test_resolve_prefers_settings_then_orcaslicer_then_english(self):
        self.assertEqual(i18n.resolve("de", "zh_CN"), "de")
        self.assertEqual(i18n.resolve("auto", "zh_TW"), "zh-CN")
        self.assertEqual(i18n.resolve("auto", "pl_PL"), "pl")
        self.assertEqual(i18n.resolve("auto", "ja_JP"), "en")
        self.assertEqual(i18n.resolve("auto", None), "en")

    def test_tr_in_each_language(self):
        text = "the printer is not connected"
        for lang in i18n.LANGUAGES:
            i18n.set_language(lang)
            self.assertEqual(i18n.language(), lang)
            got = i18n.tr(text)
            self.assertTrue(got)
            self.assertEqual(got == text, lang == "en", lang)
        i18n.set_language("xx")
        self.assertEqual(i18n.tr(text), text)
        self.assertEqual(i18n.tr("a text no catalogue has"), "a text no catalogue has")

    def test_formatted_message(self):
        i18n.set_language("de")
        msg = i18n.tr("the printer is %s; nothing was sent") % i18n.tr("printing")
        self.assertNotIn("%", msg)
        self.assertIn(i18n.CATALOGUES["de"]["printing"], msg)


if __name__ == "__main__":
    unittest.main()
