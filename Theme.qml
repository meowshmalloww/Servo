pragma Singleton

import QtQuick

QtObject {
    readonly property color window: "#080a0c"
    readonly property color chrome: "#0b0e11"
    readonly property color panel: "#0f1215"
    readonly property color panelRaised: "#12161a"
    readonly property color surface: "#15191d"
    readonly property color surfaceHover: "#1a1f24"
    readonly property color surfacePressed: "#20262c"
    readonly property color field: "#0b0e11"
    readonly property color border: "#282e34"
    readonly property color borderStrong: "#394149"

    readonly property color text: "#e6e9ec"
    readonly property color textSecondary: "#a7afb7"
    readonly property color textMuted: "#6f7881"
    readonly property color textDisabled: "#4a5158"

    readonly property color accent: "#d9822b"
    readonly property color accentBright: "#f39a3d"
    readonly property color accentDim: "#5d3517"
    readonly property color teal: "#35b8ad"
    readonly property color green: "#67bd61"
    readonly property color red: "#e2534a"
    readonly property color yellow: "#d7a33f"
    readonly property color blue: "#4e8bd8"

    readonly property string uiFont: Qt.platform.os === "windows" ? "Segoe UI Variable" : "Noto Sans"
    readonly property string monoFont: Qt.platform.os === "windows" ? "Cascadia Mono" : "Noto Sans Mono"

    readonly property int menuHeight: 30
    readonly property int toolbarHeight: 50
    readonly property int statusHeight: 28
    readonly property int panelHeaderHeight: 34
    readonly property int controlHeight: 30
    readonly property int rowHeight: 28

    function tint(color, alpha) {
        return Qt.rgba(color.r, color.g, color.b, alpha)
    }
}
