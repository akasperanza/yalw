import QtQuick
import QtQuick.Controls

Rectangle {
    id: f
    property string text: ""
    property string placeholder: ""
    signal edited(string text)
    width: 190; height: 28; radius: 8
    color: cfg.pal.raised
    border.width: input.activeFocus ? 1 : 0
    border.color: cfg.pal.accent

    TextInput {
        id: input
        anchors.fill: parent
        anchors.leftMargin: 10; anchors.rightMargin: 10
        verticalAlignment: TextInput.AlignVCenter
        text: f.text
        color: cfg.pal.text
        font.family: host.fontFamily
        font.pixelSize: 13
        clip: true
        selectByMouse: true
        onEditingFinished: f.edited(text)
    }
    Txt {
        anchors.fill: input
        verticalAlignment: Text.AlignVCenter
        visible: input.text === "" && !input.activeFocus
        text: f.placeholder
        font.pixelSize: 13
        color: cfg.pal.dim
    }
}
