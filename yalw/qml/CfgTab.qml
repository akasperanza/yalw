import QtQuick

Item {
    id: tab
    property string text: ""
    property bool on: false
    signal clicked()
    height: 40
    Txt {
        anchors.centerIn: parent
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: tab.text
        font.pixelSize: 12
        font.weight: tab.on ? Font.DemiBold : Font.Medium
        color: tab.on ? cfg.pal.text : area.containsMouse ? cfg.pal.muted : cfg.pal.dim
        Behavior on color { ColorAnimation { duration: 140 } }
    }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: tab.clicked() }
}
