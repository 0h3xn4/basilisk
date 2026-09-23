"""Tests for gui.spacecraft_template_dialog.SpacecraftTemplateDialog."""

import pytest

pytestmark = pytest.mark.requires_gui


def test_dialog_lists_every_template(qtbot):
    from missionstudio.engine.spacecraft_templates import SPACECRAFT_TEMPLATES
    from missionstudio.gui.spacecraft_template_dialog import SpacecraftTemplateDialog

    dialog = SpacecraftTemplateDialog()
    qtbot.addWidget(dialog)
    assert dialog.list_widget.count() == len(SPACECRAFT_TEMPLATES)


def test_dialog_defaults_to_first_template_selected(qtbot):
    from missionstudio.engine.spacecraft_templates import SPACECRAFT_TEMPLATES
    from missionstudio.gui.spacecraft_template_dialog import SpacecraftTemplateDialog

    dialog = SpacecraftTemplateDialog()
    qtbot.addWidget(dialog)
    assert dialog.selected_template() is SPACECRAFT_TEMPLATES[0]
    assert dialog.description_label.text() == SPACECRAFT_TEMPLATES[0].description


def test_dialog_selection_changes_description(qtbot):
    from missionstudio.engine.spacecraft_templates import SPACECRAFT_TEMPLATES
    from missionstudio.gui.spacecraft_template_dialog import SpacecraftTemplateDialog

    dialog = SpacecraftTemplateDialog()
    qtbot.addWidget(dialog)
    dialog.list_widget.setCurrentRow(len(SPACECRAFT_TEMPLATES) - 1)
    assert dialog.selected_template() is SPACECRAFT_TEMPLATES[-1]
    assert dialog.description_label.text() == SPACECRAFT_TEMPLATES[-1].description
