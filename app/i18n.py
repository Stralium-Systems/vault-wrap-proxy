"""Deployment-selected translations shared by the API and browser."""

import html
import json
import re
from functools import cache
from pathlib import Path

SUPPORTED_LANGUAGES = ("en", "fr", "es")
LOCALES = Path(__file__).parent / "static" / "locales"


def normalize_language(value: str) -> str:
    language = value.strip().lower()
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("APP_LANGUAGE must be one of: en, fr, es")
    return language


@cache
def catalog(language: str) -> dict[str, str]:
    language = normalize_language(language)
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))


def message(language: str, key: str, **values) -> str:
    text = catalog(language)[key]
    return text.format(**values) if values else text


def render_page(template: str, language: str) -> str:
    language = normalize_language(language)
    messages = catalog(language)
    template = re.sub(
        r'(<span data-i18n="([^"]+)">).*?(</span>)',
        lambda match: match[1] + html.escape(messages[match[2]]) + match[3],
        template,
        flags=re.S,
    )

    def translate_attributes(match: re.Match) -> str:
        tag = match.group()
        for attribute in ("title", "placeholder", "value"):
            key = re.search(r"\bdata-i18n-" + attribute + r'="([^"]+)"', tag)
            if key:
                value = html.escape(messages[key[1]], quote=True)
                tag = re.sub(
                    r"(?<=\s)" + attribute + r'="[^"]*"',
                    lambda _: attribute + '="' + value + '"',
                    tag,
                )
        return tag

    template = re.sub(r"<[a-zA-Z][^>]*>", translate_attributes, template)
    # JSON is data, never executable code. Escape HTML delimiters so a future
    # translation containing </script> cannot close its JSON element.
    payload = json.dumps(messages, ensure_ascii=True)
    for char, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        payload = payload.replace(char, escaped)
    replacements = {
        "__APP_LANGUAGE__": language,
        "__APP_TITLE__": html.escape(messages["site_title"]),
        "__APP_TRANSLATIONS__": payload,
    }
    return re.sub(
        r"__APP_(?:LANGUAGE|TITLE|TRANSLATIONS)__",
        lambda match: replacements[match.group()],
        template,
    )
