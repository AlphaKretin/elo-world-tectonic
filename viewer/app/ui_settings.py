"""Persists combo box / checkbox choices across launches via QSettings, so
tabs stop reverting to their hardcoded defaults every time the app starts.

Every caller follows the same pattern: wire the widget's change signal to an
expensive reload/rebuild handler, call one of these to restore last launch's
value, then invoke that handler once explicitly to establish the initial
view. If the widget's own change signal were already connected at that
point (every caller connects before binding), restoring the saved value
would fire the handler too -- once per bound widget, on top of the explicit
call these callers already make. blockSignals() during the restore is what
makes that explicit call the *only* one that fires, since it's always
present and always correct for the final restored state."""


def bind_combo(settings, key, combo):
    saved = settings.value(key)
    if saved is not None:
        idx = combo.findText(saved)
        if idx >= 0:
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
    combo.currentIndexChanged.connect(lambda _: settings.setValue(key, combo.currentText()))


def bind_checkbox(settings, key, checkbox):
    saved = settings.value(key, None, type=bool)
    if saved is not None:
        checkbox.blockSignals(True)
        checkbox.setChecked(saved)
        checkbox.blockSignals(False)
    checkbox.toggled.connect(lambda checked: settings.setValue(key, checked))


def bind_spinbox(settings, key, spinbox):
    saved = settings.value(key, None, type=int)
    if saved is not None:
        spinbox.blockSignals(True)
        spinbox.setValue(saved)
        spinbox.blockSignals(False)
    spinbox.valueChanged.connect(lambda value: settings.setValue(key, value))
