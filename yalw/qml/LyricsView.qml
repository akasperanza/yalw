import QtQuick
import QtQuick.Effects

// The lyrics card: the current line big, its neighbours small. Word-timed lyrics
// light up word by word, line-timed lyrics a line at a time.
Item {
    id: root
    readonly property bool compact: host.style.compact
    width: host.style.cardW
    height: host.style.lyricsH

    property bool active: false
    property bool hovered: false
    readonly property bool lift: hovered && host.style.hoverControls     // the media controls are up: make room for them
    property real liftY: lift ? (compact ? 10 : 16) : 0
    Behavior on liftY { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
    property var lines: []
    property bool wordMode: false
    property color accent: "#7c8cff"
    property color accentColor: accent
    Behavior on accentColor { ColorAnimation { duration: 600 } }
    property string cover: ""
    property string title: ""
    property string artist: ""
    property bool playing: false
    property real basePos: 0
    property real stamp: 0
    property real pos: 0
    property int idx: -2
    property int wordIdx: -1
    signal moved()                    // the line or the lit word changed: something is happening
    property var curWords: []
    property string prevText: ""
    property string nextText: ""
    property int curSize: 26
    property real yShift: 0

    function refresh(m) {
        accent = host.style.accent === "auto" ? m.accent : host.style.accent
        cover = m.art
        title = m.title
        artist = m.artist
        playing = m.playing
        basePos = m.position
        stamp = m.stamp
        tick()
    }

    // A new set of lyrics is about to be shown.
    function apply(l, m) {
        lines = l.lines
        wordMode = l.synced === "word"
        idx = -2
        refresh(m)
    }

    // The same song's lyrics, moved in time (the card's "earlier / later" buttons).
    function setLines(l) {
        lines = l.lines
        wordMode = l.synced === "word"
        idx = -2
        tick()
    }

    function setLine(i) {
        idx = i
        const cur = i >= 0 ? lines[i] : null
        prevText = i > 0 ? lines[i - 1].text : ""
        nextText = i + 1 < lines.length ? lines[i + 1].text : ""
        if (cur) {
            curWords = cur.words && cur.words.length ? cur.words : cur.text.split(" ").map(w => ({ t: cur.t, text: w, sp: true }))
            const n = cur.text.length * (compact ? 0.8 : 1)
            curSize = compact ? (n > 56 ? 15 : n > 30 ? 18 : 22) : (n > 60 ? 17 : n > 34 ? 21 : 26)
        } else {
            curWords = []
        }
        swap.restart()
        moved()
    }

    function tick() {
        pos = playing ? basePos + (Date.now() - stamp) / 1000 : basePos
        let found = -1
        for (let k = 0; k < lines.length; k++) {
            if (lines[k].t <= pos + 0.05) found = k; else break
        }
        if (found !== idx) setLine(found)
        if (wordMode && found >= 0 && curWords.length) {
            let w = -1
            for (let k = 0; k < curWords.length; k++) if (pos >= curWords[k].t) w = k
            if (w !== wordIdx) { wordIdx = w; moved() }
        }
    }

    Timer {
        interval: 40
        repeat: true
        running: root.active && root.playing
        onTriggered: root.tick()
    }

    // -- backdrop: the cover, blurred and darkened ----------------------------
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.darker(root.accentColor, 2.6) }
            GradientStop { position: 1.0; color: Qt.darker(root.accentColor, 5.5) }
        }
    }
    Image {
        anchors.fill: parent
        source: root.cover
        fillMode: Image.PreserveAspectCrop
        sourceSize: Qt.size(500, 500)
        layer.enabled: true
        layer.effect: MultiEffect { blurEnabled: true; blur: 0.9; blurMax: 48; saturation: 0.15 }
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0.66) }
            GradientStop { position: 0.5; color: Qt.rgba(0, 0, 0, 0.52) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.72) }
        }
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.24) }
            GradientStop { position: 0.9; color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.0) }
        }
    }

    // -- song --------------------------------------------------------------
    Txt {
        x: 24
        y: root.compact ? 11 : 15
        width: root.width - 48
        text: host.songLine.replace("{title}", root.title).replace("{artist}", root.artist)
        font.pixelSize: 11
        font.weight: Font.DemiBold
        font.letterSpacing: 0.3
        color: Qt.rgba(1, 1, 1, 0.62)
    }

    // -- lines -------------------------------------------------------------
    Txt {
        x: 24
        y: 41
        visible: !root.compact
        width: root.width - 48
        text: root.prevText
        font.pixelSize: 13
        font.weight: Font.Medium
        color: Qt.rgba(1, 1, 1, 0.38)
        opacity: root.lift ? 0.25 : 1
        Behavior on opacity { NumberAnimation { duration: 220 } }
    }
    Item {
        id: curArea
        x: 24
        y: root.compact ? 30 : 60
        width: root.width - 48
        height: root.compact ? 58 : 76
        Flow {
            width: parent.width
            y: (parent.height - height) / 2 + root.yShift - root.liftY
            Repeater {
                model: root.curWords
                delegate: Item {
                    id: slot
                    required property var modelData
                    required property int index
                    readonly property real nextT: index + 1 < root.curWords.length ? root.curWords[index + 1].t : modelData.t + 0.6
                    readonly property bool sung: root.pos >= modelData.t
                    // A word does not switch on: it fades in over the time it is sung (a line-timed line fades in as a whole).
                    readonly property real lit: root.wordMode
                        ? Math.max(0, Math.min(1, (root.pos - modelData.t) / Math.min(Math.max(nextT - modelData.t, 0.2), 0.5)))
                        : (sung ? 1 : 0)
                    width: word.implicitWidth + (modelData.sp ? root.curSize * 0.34 : 0)
                    height: word.implicitHeight
                    Txt {
                        id: word
                        text: slot.modelData.text
                        elide: Text.ElideNone
                        font.pixelSize: root.curSize
                        font.weight: Font.Bold
                        font.letterSpacing: -0.3
                        color: "white"
                        opacity: 0.32 + 0.68 * slot.lit
                        Behavior on opacity { NumberAnimation { duration: root.wordMode ? 90 : 420; easing.type: Easing.OutCubic } }
                    }
                }
            }
        }
    }
    Txt {
        x: 24
        y: root.compact ? 94 : 139
        width: root.width - 48
        text: root.nextText
        font.pixelSize: 13
        font.weight: Font.Medium
        color: Qt.rgba(1, 1, 1, 0.38)
        opacity: root.lift ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 180 } }
    }

    // -- media controls, rising from the bottom edge while the card is hovered -----------------
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: root.compact ? 62 : 84
        opacity: root.lift ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 260 } }
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0) }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.62) }
        }
    }
    Item {
        id: controls
        width: 190
        height: 60
        anchors.horizontalCenter: parent.horizontalCenter
        scale: root.compact ? 0.6 : 0.72
        y: root.height - (root.compact ? 25 : 30) - height / 2 + (root.lift ? 0 : 34)
        opacity: root.lift ? 1 : 0
        Behavior on y { NumberAnimation { duration: 340; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: 200 } }
        CtlButton { x: 0; y: 2; icon: "skip-back"; show: root.lift; delay: 0; onClicked: host.previous() }
        PlayButton { x: 65; y: 0; playing: root.playing; show: root.lift; delay: 60; onClicked: host.playPause() }
        CtlButton { x: 134; y: 2; icon: "skip-forward"; show: root.lift; delay: 120; onClicked: host.next() }
    }

    ParallelAnimation {
        id: swap
        NumberAnimation { target: root; property: "yShift"; from: 18; to: 0; duration: 420; easing.type: Easing.OutCubic }
        NumberAnimation { target: curArea; property: "opacity"; from: 0; to: 1; duration: 260 }
    }
}
