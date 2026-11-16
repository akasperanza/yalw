import QtQuick

// Compact slider with its value printed at the end.
Item {
    id: s
    property real from: 0
    property real to: 1
    property real step: 0.01
    property real value: 0
    property real factor: 1          // shown value = value * factor
    property string suffix: ""
    signal moved(real value)
    width: 210
    height: 26

    readonly property real frac: to > from ? Math.max(0, Math.min(1, (value - from) / (to - from))) : 0
    readonly property real trackW: width - 56

    function at(mx) {
        const f = Math.max(0, Math.min(1, mx / trackW))
        const raw = from + f * (to - from)
        return Math.max(from, Math.min(to, Math.round(raw / step) * step))
    }

    Rectangle {
        id: track
        width: s.trackW; height: 4; radius: 2
        y: (s.height - height) / 2
        color: cfg.pal.raised
        Rectangle { width: parent.width * s.frac; height: parent.height; radius: 2; color: cfg.pal.accent }
    }
    Rectangle {
        width: 16; height: 16; radius: 8
        x: s.trackW * s.frac - width / 2
        y: (s.height - height) / 2
        color: cfg.pal.text
        border.width: 3
        border.color: cfg.pal.panel
        scale: area.pressed ? 1.2 : area.containsMouse ? 1.1 : 1
        Behavior on scale { NumberAnimation { duration: 120 } }
    }
    Txt {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: 48
        horizontalAlignment: Text.AlignRight
        text: Math.round(s.value * s.factor * 10) / 10 + s.suffix
        font.pixelSize: 12
        color: cfg.pal.muted
    }
    MouseArea {
        id: area
        x: -8; width: s.trackW + 16; height: parent.height
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onPressed: mouse => s.moved(s.at(mouse.x - 8))
        onPositionChanged: mouse => { if (pressed) s.moved(s.at(mouse.x - 8)) }
    }
}
