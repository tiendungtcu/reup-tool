from __future__ import annotations

import json
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QObject, QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QRadioButton,
    QStatusBar,
    QTabWidget,
    QToolButton,
    QWidget,
)

from app_paths import resource_path


@dataclass
class _Binding:
    base_text: str
    setter: Callable[[str], None]
    property_name: str


class TranslationManager:
    """Load translations and update widgets when the language changes."""

    def __init__(self) -> None:
        self._translations: Dict[str, Dict[str, str]] = {}
        self._default_language: str = "en"
        self._language_labels: Dict[str, str] = {"en": "English", "vi": "Vietnamese"}
        self._widget_bindings: "weakref.WeakKeyDictionary[QObject, List[_Binding]]" = weakref.WeakKeyDictionary()
        self._tab_bindings: "weakref.WeakKeyDictionary[QTabWidget, Dict[int, str]]" = weakref.WeakKeyDictionary()
        self._action_bindings: "weakref.WeakKeyDictionary[QAction, str]" = weakref.WeakKeyDictionary()
        self._status_bindings: "weakref.WeakKeyDictionary[QStatusBar, str]" = weakref.WeakKeyDictionary()
        self._combo_bindings: "weakref.WeakKeyDictionary[QComboBox, List[Tuple[int, str]]]" = weakref.WeakKeyDictionary()
        self._callbacks: List[Callable[[str], None]] = []
        self._settings = QSettings("AutoBot", "GUI")
        self._load_translations()
        saved_language = self._settings.value("language", type=str)
        if saved_language and saved_language in self._translations:
            self._current_language = saved_language
        else:
            default = self._translations.get("default")
            if default:
                self._current_language = default.get("code", "vi")
            else:
                self._current_language = self._default_language

    @property
    def current_language(self) -> str:
        return self._current_language

    @property
    def default_language(self) -> str:
        return self._default_language

    def available_languages(self) -> Iterable[str]:
        return self._translations.keys()

    def language_label(self, language_code: str) -> str:
        base = self._language_labels.get(language_code, language_code)
        return self.gettext(base, language_code=self._current_language)

    def gettext(self, text: str, language_code: Optional[str] = None) -> str:
        if not text:
            return text
        lang = language_code or self._current_language
        lang_map = self._translations.get(lang)
        if lang_map and text in lang_map:
            return lang_map[text]
        english_map = self._translations.get("en", {})
        if lang != "en" and text in english_map:
            return english_map[text]
        return text

    def set_language(self, language_code: str) -> None:
        if language_code not in self._translations:
            return
        if language_code == self._current_language:
            return
        self._current_language = language_code
        self._settings.setValue("language", language_code)
        self._apply_language()
        for callback in list(self._callbacks):
            try:
                callback(language_code)
            except Exception:
                pass

    def register_callback(self, callback: Callable[[str], None]) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def bind_widget_tree(self, root: QWidget) -> None:
        queue: List[QWidget] = [root]
        visited: set[int] = set()
        while queue:
            widget = queue.pop()
            if id(widget) in visited:
                continue
            visited.add(id(widget))
            self._capture_widget(widget)
            for action in getattr(widget, "actions", lambda: [])():
                self._capture_action(action)
            if isinstance(widget, QDialogButtonBox):
                for button in widget.buttons():
                    self._capture_widget(button)
            if isinstance(widget, QTabWidget):
                self._capture_tab_widget(widget)
            for child in widget.findChildren(QWidget):
                queue.append(child)
        self._apply_language()

    def clear_callbacks(self) -> None:
        self._callbacks.clear()

    def _load_translations(self) -> None:
        translation_path = resource_path("resources", "i18n", "translations.json")
        try:
            with open(translation_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except FileNotFoundError:
            payload = {}
        except json.JSONDecodeError:
            payload = {}
        languages = payload.get("languages", {})
        if isinstance(languages, dict):
            self._translations = {
                code: mapping if isinstance(mapping, dict) else {}
                for code, mapping in languages.items()
            }
        else:
            self._translations = {}
        default = payload.get("default_language")
        if isinstance(default, str) and default in self._translations:
            self._default_language = default
        else:
            self._default_language = "vi" if "vi" in self._translations else "en"
        if "en" not in self._translations:
            self._translations["en"] = {}
        if "vi" not in self._translations and self._default_language == "vi":
            self._translations["vi"] = {}

    def _capture_widget(self, widget: QWidget) -> None:
        binding_list = self._widget_bindings.setdefault(widget, [])

        def add_binding(setter: Callable[[str], None], base_text: str, prop: str) -> None:
            if not base_text:
                return
            for existing in binding_list:
                if existing.property_name == prop:
                    return
            binding_list.append(_Binding(base_text=base_text, setter=setter, property_name=prop))

        if hasattr(widget, "windowTitle") and callable(widget.windowTitle):
            title = widget.windowTitle()
            if title:
                add_binding(widget.setWindowTitle, title, "windowTitle")

        if isinstance(widget, QGroupBox):
            title = widget.title()
            if title:
                add_binding(widget.setTitle, title, "title")

        if isinstance(widget, (QLabel, QPushButton, QRadioButton, QToolButton)):
            text = widget.text()
            if text:
                add_binding(widget.setText, text, "text")

        if isinstance(widget, QAbstractButton) and not isinstance(widget, (QRadioButton, QPushButton, QToolButton)):
            text = widget.text()
            if text:
                add_binding(widget.setText, text, "text")

        if isinstance(widget, QMenu):
            text = widget.title()
            if text:
                add_binding(widget.setTitle, text, "title")

        if isinstance(widget, QStatusBar):
            message = widget.currentMessage()
            if message:
                self._status_bindings[widget] = message

        if isinstance(widget, QLineEdit):
            placeholder = widget.placeholderText()
            if placeholder:
                add_binding(widget.setPlaceholderText, placeholder, "placeholder")

        if isinstance(widget, QComboBox):
            items: List[Tuple[int, str]] = []
            for index in range(widget.count()):
                text = widget.itemText(index)
                if text:
                    items.append((index, text))
            if items:
                self._combo_bindings[widget] = items

    def _capture_action(self, action: QAction) -> None:
        if not isinstance(action, QAction):
            return
        text = action.text()
        if not text:
            return
        if action not in self._action_bindings:
            self._action_bindings[action] = text
        menu = action.menu()
        if isinstance(menu, QMenu):
            self._capture_widget(menu)

    def _capture_tab_widget(self, widget: QTabWidget) -> None:
        tab_map = self._tab_bindings.setdefault(widget, {})
        for index in range(widget.count()):
            label = widget.tabText(index)
            if label and index not in tab_map:
                tab_map[index] = label

    def _apply_language(self) -> None:
        for widget, bindings in list(self._widget_bindings.items()):
            if widget is None:
                continue
            for binding in bindings:
                translated = self.gettext(binding.base_text)
                try:
                    binding.setter(translated)
                except RuntimeError:
                    pass
        for tab_widget, label_map in list(self._tab_bindings.items()):
            if tab_widget is None:
                continue
            for index, base in label_map.items():
                translated = self.gettext(base)
                try:
                    tab_widget.setTabText(index, translated)
                except RuntimeError:
                    pass
        for action, base in list(self._action_bindings.items()):
            translated = self.gettext(base)
            try:
                action.setText(translated)
            except RuntimeError:
                pass
        for status_bar, base in list(self._status_bindings.items()):
            translated = self.gettext(base)
            try:
                status_bar.showMessage(translated)
            except RuntimeError:
                pass
        for combo, items in list(self._combo_bindings.items()):
            for index, base in items:
                translated = self.gettext(base)
                try:
                    combo.setItemText(index, translated)
                except RuntimeError:
                    continue


def tr(text: str) -> str:
    return translator.gettext(text)


translator = TranslationManager()
