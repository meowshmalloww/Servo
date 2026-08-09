# Servo frontend architecture

Servo's desktop interface is a Qt 6/QML workbench organized around one persistent shell and five task-oriented workspaces.

## Visual system

- Near-black chrome and graphite panels reduce glare and keep imagery and evidence legible.
- Orange marks current selection, active work, and actionable warnings.
- Teal is reserved for perception and measured telemetry.
- Green and red communicate verified pass and failure states.
- Compact typography, one-pixel borders, and square controls follow professional simulation and game-engine tools rather than consumer dashboard cards.

The shared tokens live in `Theme.qml`. Reusable controls intentionally wrap Qt Quick primitives so states, spacing, typography, and focus behavior remain consistent.

## Shell and navigation

`Main.qml` owns the standard menu bar, project header, workspace tabs, activity rail, status strip, preferences, keyboard shortcuts, and dynamic workspace loader. Workspace state is restored with `QtCore.Settings`.

The five workspace components are independent views:

- `PrepareWorkspace.qml`
- `SimulateWorkspace.qml`
- `DiagnoseWorkspace.qml`
- `TrainWorkspace.qml`
- `VerifyWorkspace.qml`

Each uses Qt `SplitView` panes so the outliner, work area, and inspector can be resized without custom docking logic. Vertical work areas use the same pattern for viewports, timelines, telemetry, logs, and evidence tables.

## Reusable editor components

- `EngineViewport.qml`: camera fixture, detection box, trajectory, viewport actions, and legend.
- `TimelinePanel.qml`: playback state, seek interaction, event lanes, and current-frame marker.
- `MetricPlot.qml`: compact telemetry and training charts.
- `ConfigSection.qml` and `PropertyRow.qml`: collapsible inspector and configuration forms.
- `TreeRow.qml`: compact outliner/job/checkpoint rows.
- `PanelFrame.qml`, `PanelHeader.qml`, and `PaneDivider.qml`: pane structure.
- `AppButton.qml`, `IconButton.qml`, `ServoSearchField.qml`, `UiTextField.qml`, and `UiComboBox.qml`: shared controls.

## Backend integration boundary

The current workspace data is deliberately local and deterministic. Backend work can replace each fixture with C++ models or QML-facing service objects without redesigning the shell. Long-running work should expose explicit states such as queued, running, failed, and complete; the frontend already renders those states and should not infer them from logs.

The optional `SERVO_QML_LOG` environment variable enables a file-backed Qt message handler for automated runtime QA. It is inactive during normal launches.
