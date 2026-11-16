import QtQuick

// Title + artist. Two of these trade places when the song changes.
Item {
    id: blk
    property string title: ""
    property string artist: ""
    property bool compact: false
    opacity: 0

    function show(t, a, dir, animate) {
        title = t
        artist = a
        hideAnim.stop()
        if (!animate) { x = 0; opacity = 1; return }
        x = dir * 38
        opacity = 0
        showAnim.restart()
    }

    function hide(dir) {
        showAnim.stop()
        hideAnim.toX = -dir * 38
        hideAnim.restart()
    }

    Txt {
        width: parent.width
        text: blk.title
        font.pixelSize: blk.compact ? 22 : 28
        fontSizeMode: Text.HorizontalFit          // a long title shrinks to fit before it gets cut off
        minimumPixelSize: blk.compact ? 15 : 19
        font.weight: Font.Bold
        font.letterSpacing: -0.5
    }
    Txt {
        y: blk.compact ? 29 : 37
        width: parent.width
        text: blk.artist
        font.pixelSize: blk.compact ? 14 : 16
        font.weight: Font.Medium
        color: Qt.rgba(1, 1, 1, 0.74)
    }

    ParallelAnimation {
        id: showAnim
        NumberAnimation { target: blk; property: "x"; to: 0; duration: 520; easing.type: Easing.OutCubic }
        SequentialAnimation {
            PauseAnimation { duration: 70 }
            NumberAnimation { target: blk; property: "opacity"; to: 1; duration: 340 }
        }
    }
    ParallelAnimation {
        id: hideAnim
        property real toX: 0
        NumberAnimation { target: blk; property: "x"; to: hideAnim.toX; duration: 300; easing.type: Easing.InCubic }
        NumberAnimation { target: blk; property: "opacity"; to: 0; duration: 220 }
    }
}
