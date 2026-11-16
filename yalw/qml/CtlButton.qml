import QtQuick

// Skip button. Pops in with a stagger when the card is hovered.
Item {
    id: btn
    property string icon: "skip-forward"
    property int delay: 0
    property bool show: false
    signal clicked()

    width: 56
    height: 56
    opacity: 0
    scale: 0.6

    onShowChanged: {
        showAnim.stop()
        hideAnim.stop()
        if (show) showAnim.restart(); else hideAnim.restart()
    }

    SequentialAnimation {
        id: showAnim
        PauseAnimation { duration: btn.delay }
        ParallelAnimation {
            NumberAnimation { target: btn; property: "opacity"; to: 1; duration: 180 }
            NumberAnimation { target: btn; property: "scale"; to: 1; duration: 440; easing.type: Easing.OutBack; easing.overshoot: 2.2 }
        }
    }
    ParallelAnimation {
        id: hideAnim
        NumberAnimation { target: btn; property: "opacity"; to: 0; duration: 140 }
        NumberAnimation { target: btn; property: "scale"; to: 0.75; duration: 140 }
    }

    Item {
        anchors.fill: parent
        scale: area.pressed ? 0.82 : (area.containsMouse ? 1.14 : 1.0)
        Behavior on scale { NumberAnimation { duration: 170; easing.type: Easing.OutBack; easing.overshoot: 3 } }

        Rectangle {
            anchors.centerIn: parent
            width: 46; height: 46; radius: 23
            color: Qt.rgba(1, 1, 1, area.containsMouse ? 0.17 : 0)
            Behavior on color { ColorAnimation { duration: 150 } }
        }
        Icon {
            anchors.centerIn: parent
            name: btn.icon
            size: 28
            filled: true
            stroke: 1.5
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        enabled: btn.show
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.clicked()
    }
}
