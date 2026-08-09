pragma Singleton

import QtQuick

QtObject {
    readonly property color window: "#191b1d"
    readonly property color chrome: "#1d2023"
    readonly property color panel: "#222528"
    readonly property color panelRaised: "#272a2e"
    readonly property color panelHover: "#2c3034"
    readonly property color field: "#1b1d20"
    readonly property color fieldHover: "#202327"

    readonly property color border: "#3a3e43"
    readonly property color borderSoft: "#30343a"
    readonly property color borderStrong: "#4a4f55"

    readonly property color text: "#d6d9dc"
    readonly property color textSecondary: "#aeb4ba"
    readonly property color textMuted: "#7f878f"
    readonly property color textDisabled: "#5e656c"

    readonly property color accent: "#4d7fae"
    readonly property color accentHover: "#5b8cba"
    readonly property color selection: "#29415a"
    readonly property color selectionBorder: "#4f7da8"

    readonly property color success: "#71a866"
    readonly property color warning: "#d29a4a"
    readonly property color error: "#c76666"
    readonly property color info: "#6f9bc4"

    readonly property string uiFont: "Segoe UI"
    readonly property string monoFont: "Cascadia Mono"

    readonly property int menuHeight: 30
    readonly property int topBarHeight: 56
    readonly property int toolbarHeight: 44
    readonly property int statusHeight: 24
    readonly property int panelHeaderHeight: 32
    readonly property int controlHeight: 30
    readonly property int rowHeight: 30

    readonly property int cornerControl: 2
    readonly property int cornerPopup: 3

    function icon(name) {
        return Qt.resolvedUrl("icons/" + name + ".svg")
    }
}
