import QtQuick

// The big round play/pause button; the glyph morphs when the state flips.
Item {
    id: btn
    property bool playing: false
    property bool show: false
    property int delay: 60
    signal clicked()

    width: 60
    height: 60
    opacity: 0
    scale: 0.6

    onShowChanged: {
        showAnim.stop()
        hideAnim.stop()
        if (show) showAnim.restart(); else hideAnim.restart()
    }
    onPlayingChanged: if (show) pulse.restart()

    SequentialAnimation {
        id: showAnim
        PauseAnimation { duration: btn.delay }
        ParallelAnimation {
            NumberAnimation { target: btn; property: "opacity"; to: 1; duration: 180 }
            NumberAnimation { target: btn; property: "scale"; to: 1; duration: 460; easing.type: Easing.OutBack; easing.overshoot: 2.4 }
        }
    }
    ParallelAnimation {
        id: hideAnim
        NumberAnimation { target: btn; property: "opacity"; to: 0; duration: 140 }
        NumberAnimation { target: btn; property: "scale"; to: 0.75; duration: 140 }
    }

    Rectangle {
        id: ring
        anchors.centerIn: parent
        width: 56; height: 56; radius: 28
        color: "transparent"
        border.width: 2
        border.color: "white"
        opacity: 0
    }
    ParallelAnimation {
        id: pulse
        NumberAnimation { target: ring; property: "opacity"; from: 0.6; to: 0; duration: 560; easing.type: Easing.OutQuad }
        NumberAnimation { target: ring; property: "scale"; from: 1; to: 1.55; duration: 560; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.centerIn: parent
        width: 56; height: 56; radius: 28
        color: "white"
        scale: area.pressed ? 0.9 : (area.containsMouse ? 1.07 : 1.0)
        Behavior on scale { NumberAnimation { duration: 170; easing.type: Easing.OutBack; easing.overshoot: 3 } }

        Icon {
            anchors.centerIn: parent
            name: "pause"
            tint: "#0b0b0e"
            size: 26
            filled: true
            stroke: 1.5
            opacity: btn.playing ? 1 : 0
            scale: btn.playing ? 1 : 0.4
            rotation: btn.playing ? 0 : -50
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Behavior on scale { NumberAnimation { duration: 320; easing.type: Easing.OutBack } }
            Behavior on rotation { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
        }
        Icon {
            anchors.centerIn: parent
            anchors.horizontalCenterOffset: 2
            name: "play"
            tint: "#0b0b0e"
            size: 26
            filled: true
            stroke: 1.5
            opacity: btn.playing ? 0 : 1
            scale: btn.playing ? 0.4 : 1
            rotation: btn.playing ? 50 : 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Behavior on scale { NumberAnimation { duration: 320; easing.type: Easing.OutBack } }
            Behavior on rotation { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
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
