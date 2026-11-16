import QtQuick

// A Lucide icon, recoloured and rasterised by the image provider.
Image {
    id: root
    property string name: "music"
    property color tint: "white"
    property real size: 24
    property bool filled: false
    property real stroke: 2

    function hex(c) {
        const h = v => ("0" + Math.round(v * 255).toString(16)).slice(-2)
        return h(c.r) + h(c.g) + h(c.b)
    }

    width: size
    height: size
    readonly property real px: size * Math.max(2, Screen.devicePixelRatio)
    sourceSize: Qt.size(px, px)
    source: "image://lucide/" + name + "?color=" + hex(tint) + "&fill=" + (filled ? 1 : 0) + "&sw=" + stroke
    smooth: true
    cache: true
}
