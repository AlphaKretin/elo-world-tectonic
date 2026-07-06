"""Persists combo box / checkbox choices across launches via QSettings, so
tabs stop reverting to their hardcoded defaults every time the app starts."""


def bind_combo(settings, key, combo):
    saved = settings.value(key)
    if saved is not None:
        idx = combo.findText(saved)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    combo.currentIndexChanged.connect(lambda _: settings.setValue(key, combo.currentText()))


def bind_checkbox(settings, key, checkbox):
    saved = settings.value(key, None, type=bool)
    if saved is not None:
        checkbox.setChecked(saved)
    checkbox.toggled.connect(lambda checked: settings.setValue(key, checked))
