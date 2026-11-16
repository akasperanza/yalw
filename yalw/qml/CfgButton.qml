import QtQuick

// A small button; `quiet` drops the background until it is hovered.
Rectangle {
    id: b
    property string text: ""
    property string icon: ""
    property bool quiet: false
    property bool enabled: true
    signal clicked()
    width: line.width + 28
    height: 30
    radius: 9
    opacity: enabled ? 1 : 0.4
    color: area.containsMouse && enabled ? cfg.pal.hover : quiet ? "transparent" : cfg.pal.raised
    Behavior on color { ColorAnimation { duration: 120 } }
    Row {
        id: line
        anchors.centerIn: parent
        spacing: 7
        Icon { visible: b.icon !== ""; name: b.icon; size: 13; tint: cfg.pal.muted; anchors.verticalCenter: parent.verticalCenter }
        Txt { text: b.text; font.pixelSize: 12; color: b.quiet ? cfg.pal.muted : cfg.pal.text; anchors.verticalCenter: parent.verticalCenter }
    }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; enabled: b.enabled; cursorShape: Qt.PointingHandCursor; onClicked: b.clicked() }
}
