import QtQuick

// A paragraph of explanation, set in the same quiet type as the row descriptions.
Item {
    id: note
    property alias text: body.text
    property alias tone: body.color
    width: parent ? parent.width : 400
    height: body.height + 24
    Rectangle { visible: !!parent && parent.children[0] !== note; width: parent.width; height: 1; color: cfg.pal.line }
    Txt {
        id: body
        y: 12
        width: parent.width
        wrapMode: Text.WordWrap
        maximumLineCount: 14
        font.pixelSize: 12
        lineHeight: 1.15
        color: cfg.pal.dim
    }
}
