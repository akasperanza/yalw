import QtQuick

// A titled panel; the rows inside it are divided by hairlines.
Item {
    id: sec
    property string title: ""
    default property alias rows: col.data
    width: parent ? parent.width : 400
    height: head.height + panel.height + 20

    Txt {
        id: head
        height: 30
        verticalAlignment: Text.AlignVCenter
        text: sec.title
        font.pixelSize: 14
        font.weight: Font.DemiBold
        color: cfg.pal.text
    }
    Rectangle {
        id: panel
        y: head.height
        width: parent.width
        height: col.height
        radius: 14
        color: cfg.pal.panel
        border.color: cfg.pal.line
        Column {
            id: col
            x: 16
            width: parent.width - 32
        }
    }
}
