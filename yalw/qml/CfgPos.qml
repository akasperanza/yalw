import QtQuick

// A tiny screen; click the spot where the cards should appear.
Item {
    id: p
    property string current: "top-center"
    signal picked(string value)
    width: 168; height: 104

    readonly property var spots: [["top-left", "top-center", "top-right"], ["bottom-left", "bottom-center", "bottom-right"]]

    Rectangle {
        anchors.fill: parent
        radius: 10
        color: cfg.pal.bg
        border.color: cfg.pal.line
        Grid {
            anchors.fill: parent
            anchors.margins: 8
            columns: 3
            rows: 2
            spacing: 6
            Repeater {
                model: 6
                delegate: Rectangle {
                    id: cell
                    required property int index
                    readonly property string value: p.spots[Math.floor(index / 3)][index % 3]
                    readonly property bool on: value === p.current
                    width: (parent.width - 12) / 3; height: (parent.height - 6) / 2
                    radius: 6
                    color: on ? Qt.alpha(cfg.pal.accent, 0.22) : (area.containsMouse ? cfg.pal.hover : cfg.pal.raised)
                    Behavior on color { ColorAnimation { duration: 140 } }
                    Rectangle {
                        width: 26; height: 9; radius: 4.5
                        visible: cell.on
                        color: cfg.pal.accent
                        anchors.margins: 6
                        anchors.top: cell.index < 3 ? parent.top : undefined
                        anchors.bottom: cell.index < 3 ? undefined : parent.bottom
                        anchors.left: cell.index % 3 === 0 ? parent.left : undefined
                        anchors.right: cell.index % 3 === 2 ? parent.right : undefined
                        anchors.horizontalCenter: cell.index % 3 === 1 ? parent.horizontalCenter : undefined
                    }
                    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: p.picked(cell.value) }
                }
            }
        }
    }
}
