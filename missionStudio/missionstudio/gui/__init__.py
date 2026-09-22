"""missionStudio's PySide6 GUI shell (Phase 1).

Deliberately thin: every widget here reads/writes plain
``missionstudio.schema`` dataclasses and calls
``missionstudio.engine.service.SimulationService`` for anything that
needs Basilisk -- there is no GUI-only copy of scenario state or
simulation logic. See ``main_window.MainWindow`` for how the pieces fit
together, and ``../README.md``'s Phase 1 section for what is and isn't
in scope.
"""
