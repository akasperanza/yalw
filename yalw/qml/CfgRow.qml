import QtQuick

// One setting: its name (and what it does) on the left, the control on the right.
Item {
    id: row
    property string label: ""
    property string desc: ""
    default property alias content: slot.data
    readonly property bool first: !parent || parent.children[0] === row
    width: parent ? parent.width : 400
    height: Math.max(48, words.height + 22, slot.height + 20)

    Rectangle { visible: !row.first; width: parent.width; height: 1; color: cfg.pal.line }

    Column {
        id: words
        anchors.left: parent.left
        anchors.right: slot.left
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 3
        Txt {
            width: parent.width
            text: row.label
            font.pixelSize: 13
            color: cfg.pal.text
        }
        Txt {
            visible: row.desc !== ""
            width: parent.width
            text: row.desc
            wrapMode: Text.WordWrap
            maximumLineCount: 3
            font.pixelSize: 12
            lineHeight: 1.1
            color: cfg.pal.dim
        }
    }
    Item {
        id: slot
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: childrenRect.width
        height: childrenRect.height
    }
}
