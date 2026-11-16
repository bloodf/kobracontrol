"""The plugin's own texts in the page's five languages: what OrcaSlicer's Print dialog shows while a job runs, and
the errors and notices the tab shows inside its own sentences. Free of the `orca` module.

English is the source: `tr("the printer is not connected")` returns the text in the current language, or the
English text itself when a catalogue has no entry. Texts with values keep their % placeholders, in the same order
in every language: `tr("slot %d is empty") % 3`. A module-level constant is marked with `lazy(...)` and passed to
`tr()` where it is used, because the language is only known once OrcaSlicer runs the plugin. What the printer,
Spoolman or the operating system say (names, file names, firmware texts, their error details) is never translated.
The log stays as written: an error's text is logged in the language it was shown in."""

import lang_de
import lang_es
import lang_pt_br
import lang_zh_cn

LANGUAGES = ("en", "pt-BR", "es", "de", "zh-CN")
CATALOGUES = {"pt-BR": lang_pt_br.TEXT, "es": lang_es.TEXT, "de": lang_de.TEXT, "zh-CN": lang_zh_cn.TEXT}
# kobra.State.view()["state"], named inside sentences such as "the printer is %s; nothing was sent"
STATES = ("idle", "printing", "paused", "finished", "cancelled", "error", "offline", "busy")
_BY_BASE = {"en": "en", "pt": "pt-BR", "es": "es", "de": "de", "zh": "zh-CN"}   # zh_TW reads zh-CN rather than English
_language = "en"


def normalize(code):
    """OrcaSlicer's or a system's language code as one of LANGUAGES: "pt_BR" -> "pt-BR", "zh_TW" -> "zh-CN",
    "de_DE" -> "de"; None for a language the plugin has no texts for."""
    if not isinstance(code, str):
        return None
    return _BY_BASE.get(code.strip().replace("_", "-").lower().split("-", 1)[0])


def resolve(preference, host_language):
    """The language to use: the choice made in Settings, else OrcaSlicer's own language, else English."""
    return preference if preference in LANGUAGES else normalize(host_language) or "en"


def set_language(language):
    global _language
    _language = language if language in LANGUAGES else "en"


def language():
    return _language


def tr(text):
    return CATALOGUES.get(_language, {}).get(text, text)


def lazy(text):
    """Marks a text kept in a constant: `tr()` it where it is used (tests/test_i18n.py finds it by this call)."""
    return text
