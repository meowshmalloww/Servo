pragma Singleton

import QtQuick

QtObject {
    // ------------------------------------------------------------------
    // Servo design system - pure monochrome, dual theme.
    // Dark: neutral charcoal surfaces, white accent.
    // Light: warm-neutral paper surfaces, black accent.
    // No blue, no green - status colors are limited to functional
    // warning (amber) and error (soft red); success/info are neutral.
    // ------------------------------------------------------------------

    property bool dark: true

    // Surfaces
    readonly property color window: dark ? "#131313" : "#f2f1ee"
    readonly property color chrome: dark ? "#1a1a1b" : "#e9e7e3"
    readonly property color panel: dark ? "#202021" : "#f7f6f3"
    readonly property color panelRaised: dark ? "#28282a" : "#ffffff"
    readonly property color panelHover: dark ? "#313134" : "#eceae5"
    readonly property color field: dark ? "#1b1b1c" : "#fbfaf7"
    readonly property color fieldHover: dark ? "#242426" : "#f1efe9"

    // The 3D viewport stays dark in both themes - it is a render surface.
    readonly property color viewport: "#101011"
    readonly property color viewportGrid: "#3a3a3d"

    // Hairlines exist only where a surface step cannot separate regions.
    readonly property color border: dark ? "#2c2c2f" : "#dedbd5"
    readonly property color borderSoft: dark ? "#222225" : "#e6e4df"
    readonly property color borderStrong: dark ? "#3d3d41" : "#c9c5bd"

    // Text
    readonly property color text: dark ? "#f0f0ee" : "#1c1c1a"
    readonly property color textSecondary: dark ? "#b9b9b5" : "#565651"
    readonly property color textMuted: dark ? "#8b8b87" : "#8a887f"
    readonly property color textDisabled: dark ? "#60605c" : "#bab8b0"

    // Monochrome accent - white on dark, black on light.
    readonly property color accent: dark ? "#ededeb" : "#1a1a19"
    readonly property color accentHover: dark ? "#ffffff" : "#000000"
    readonly property color accentPress: dark ? "#d9d9d6" : "#333332"
    readonly property color accentText: dark ? "#161616" : "#ffffff"
    readonly property color selection: dark ? "#2e2e30" : "#e9e7e1"
    readonly property color selectionBorder: dark ? "#8a8a88" : "#a09c93"
    readonly property color accentDim: dark ? "#98989a" : "#77756d"

    // Functional status colors - deliberately quiet, never decorative.
    readonly property color success: dark ? "#d6d8d2" : "#45483f"
    readonly property color warning: dark ? "#d2a35c" : "#9a6b15"
    readonly property color error: dark ? "#d3776c" : "#b04a3e"
    readonly property color info: dark ? "#c6c6c2" : "#6d6b64"

    // Soft tinted fills for status surfaces (badges, chips, banners).
    readonly property color tintSuccess: dark ? "#292b28" : "#edeee8"
    readonly property color tintWarning: dark ? "#332a1a" : "#f7edd8"
    readonly property color tintError: dark ? "#342421" : "#f8e7e2"
    readonly property color tintInfo: dark ? "#2a2b2a" : "#eeeeec"

    // Translucent HUD surfaces floating over the (always dark) viewport.
    readonly property color overlayHud: "#e01a1a1c"
    readonly property color overlayWarn: "#de33291a"

    readonly property string uiFont: "Segoe UI"
    readonly property string monoFont: "Cascadia Mono"

    // ------------------------------------------------------------------
    // Metrics
    // ------------------------------------------------------------------
    readonly property int menuHeight: 30
    readonly property int topBarHeight: 44
    readonly property int toolbarHeight: 42
    readonly property int statusHeight: 26
    readonly property int panelHeaderHeight: 36
    readonly property int controlHeight: 30
    readonly property int rowHeight: 30
    readonly property int railWidth: 54

    // Icon ladder - icons sit small and quiet, never dominating a control.
    readonly property int iconXs: 12
    readonly property int iconSm: 13
    readonly property int iconMd: 14
    readonly property int iconLg: 15
    readonly property int iconXl: 17

    readonly property color iconDefault: textSecondary

    // Corner language - soft rounding everywhere, strongest on floating layers.
    readonly property int cornerControl: 6
    readonly property int cornerCard: 10
    readonly property int cornerPopup: 12
    readonly property int cornerTile: 8

    // ------------------------------------------------------------------
    // Motion - short, soft, consistent. Users can disable non-essential motion.
    // ------------------------------------------------------------------
    property bool motionEnabled: true
    readonly property int animFast: motionEnabled ? 130 : 0
    readonly property int animBase: motionEnabled ? 190 : 0
    readonly property int animSlow: motionEnabled ? 300 : 0
    readonly property int animMove: motionEnabled ? 240 : 0

    function icon(name) {
        return Qt.resolvedUrl("icons/" + name + ".svg");
    }

    readonly property url appLogo: Qt.resolvedUrl("assets/servo-logo.png")
}
