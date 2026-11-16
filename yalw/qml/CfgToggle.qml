import QtQuick

Item {
    id: t
    property bool checked: false
    signal toggled(bool value)
    width: 40
    height: 24

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: t.checked ? cfg.pal.accent : cfg.pal.raised
        border.width: t.checked ? 0 : 1
        border.color: cfg.pal.line
        Behavior on color { ColorAnimation { duration: 160 } }
        Rectangle {
            width: 18; height: 18; radius: 9
            y: 3
            x: t.checked ? parent.width - width - 3 : 3
            color: t.checked ? cfg.pal.onAccent : cfg.pal.muted
            Behavior on x { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: 160 } }
        }
    }
    MouseArea {
        anchors.fill: parent
        anchors.margins: -4
        cursorShape: Qt.PointingHandCursor
        onClicked: t.toggled(!t.checked)
    }
}
