pragma Singleton

import QtQuick

QtObject {
    readonly property color window: "#141617"
    readonly property color chrome: "#191c1e"
    readonly property color panel: "#1e2123"
    readonly property color panelRaised: "#24282b"
    readonly property color panelHover: "#2b3034"
    readonly property color field: "#17191b"
    readonly property color fieldHover: "#202427"
    readonly property color viewport: "#101213"
    readonly property color viewportGrid: "#34393d"

    readonly property color border: "#373c40"
    readonly property color borderSoft: "#2b3034"
    readonly property color borderStrong: "#4a5055"

    readonly property color text: "#e2e5e7"
    readonly property color textSecondary: "#b4bac0"
    readonly property color textMuted: "#858d94"
    readonly property color textDisabled: "#626a71"

    readonly property color accent: "#4f7699"
    readonly property color accentHover: "#5c84a8"
    readonly property color selection: "#263c50"
    readonly property color selectionBorder: "#6288aa"

    readonly property color success: "#71a866"
    readonly property color warning: "#d29a4a"
    readonly property color error: "#c76666"
    readonly property color info: "#6f9bc4"

    readonly property string uiFont: "Segoe UI"
    readonly property string monoFont: "Cascadia Mono"

    readonly property int menuHeight: 28
    readonly property int topBarHeight: 42
    readonly property int toolbarHeight: 38
    readonly property int statusHeight: 24
    readonly property int panelHeaderHeight: 32
    readonly property int controlHeight: 28
    readonly property int rowHeight: 28

    readonly property int cornerControl: 3
    readonly property int cornerPopup: 6

    function icon(name) {
        return Qt.resolvedUrl("icons/" + name + ".svg");
    }
}
