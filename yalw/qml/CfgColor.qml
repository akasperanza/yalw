import QtQuick

// Preset swatches plus a hex field.
Row {
    id: c
    property string color: "#4d8dff"
    signal picked(string hex)
    spacing: 6
    readonly property var presets: ["#4d8dff", "#a855f7", "#ec4899", "#ef4444", "#f59e0b", "#22c55e", "#14b8a6", "#e5e7eb"]

    Repeater {
        model: c.presets
        delegate: Rectangle {
            required property string modelData
            width: 18; height: 18; radius: 9
            color: modelData
            border.width: modelData === c.color.toLowerCase() ? 2 : 0
            border.color: cfg.pal.text
            anchors.verticalCenter: parent.verticalCenter
            scale: sw.containsMouse ? 1.15 : 1
            Behavior on scale { NumberAnimation { duration: 100 } }
            MouseArea { id: sw; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: c.picked(parent.modelData) }
        }
    }
    CfgField {
        width: 78
        text: c.color
        placeholder: "#rrggbb"
        onEdited: t => { if (/^#[0-9a-fA-F]{6}$/.test(t)) c.picked(t.toLowerCase()) }
    }
}
