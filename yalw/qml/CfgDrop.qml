import QtQuick
import QtQuick.Controls

// Drop-down list: model = [{value, text}].
Item {
    id: d
    property var model: []
    property var current
    property int popupWidth: 200
    signal picked(var value)
    width: Math.max(110, Math.min(popupWidth, text.implicitWidth + 44))
    height: 28

    function labelFor(v) {
        for (let i = 0; i < model.length; i++) if (model[i].value === v) return model[i].text
        return String(v)
    }

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: area.containsMouse || pop.visible ? cfg.pal.hover : cfg.pal.raised
        Behavior on color { ColorAnimation { duration: 120 } }
        Txt {
            id: text
            x: 10
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 34
            text: d.labelFor(d.current)
            font.pixelSize: 13
            color: cfg.pal.text
        }
        Icon {
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            name: "chevron-down"; size: 14; tint: cfg.pal.muted; stroke: 2.2
            rotation: pop.visible ? 180 : 0
            Behavior on rotation { NumberAnimation { duration: 160 } }
        }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: pop.visible ? pop.close() : pop.open()
    }

    Popup {
        id: pop
        y: d.height + 4
        x: d.width - width
        width: Math.max(d.width, d.popupWidth)
        height: Math.min(list.contentHeight + 8, 240)
        padding: 4
        background: Rectangle { radius: 11; color: cfg.pal.panel; border.color: cfg.pal.line }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 120 } }
        contentItem: ListView {
            id: list
            clip: true
            model: d.model
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            delegate: Rectangle {
                required property var modelData
                width: list.width; height: 28; radius: 6
                color: hover.hovered ? cfg.pal.hover : "transparent"
                HoverHandler { id: hover }
                Txt {
                    x: 8
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 16
                    text: parent.modelData.text
                    font.pixelSize: 13
                    color: parent.modelData.value === d.current ? cfg.pal.accent : cfg.pal.text
                }
                TapHandler { onTapped: { d.picked(parent.modelData.value); pop.close() } }
            }
        }
    }
}
