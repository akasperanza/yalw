import QtQuick

// Segmented control: model = [{value, text}].
Rectangle {
    id: seg
    property var model: []
    property var current
    signal picked(var value)
    height: 30
    width: row.width + 6
    radius: 9
    color: cfg.pal.raised

    Row {
        id: row
        x: 3; y: 3
        spacing: 0
        Repeater {
            model: seg.model
            delegate: Rectangle {
                required property var modelData
                readonly property bool on: modelData.value === seg.current
                width: label.implicitWidth + 24; height: 24; radius: 7
                color: on ? cfg.pal.hover : "transparent"
                Behavior on color { ColorAnimation { duration: 140 } }
                Txt {
                    id: label
                    anchors.centerIn: parent
                    text: parent.modelData.text
                    font.pixelSize: 12
                    font.weight: parent.on ? Font.DemiBold : Font.Normal
                    color: parent.on ? cfg.pal.text : cfg.pal.muted
                }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: seg.picked(parent.modelData.value) }
            }
        }
    }
}
