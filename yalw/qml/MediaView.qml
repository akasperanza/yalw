import QtQuick
import QtQuick.Effects

// The "now playing" card: full-bleed cover, title, progress, hover controls.
Item {
    id: root
    readonly property bool compact: host.style.compact
    width: host.style.cardW
    height: host.style.mediaH

    property bool hovered: false
    property bool active: false          // the window is on screen; keeps hidden cards from animating
    readonly property bool dragging: seek.pressed

    // -- state -------------------------------------------------------------
    property color accent: "#7c8cff"
    property color accentColor: accent
    Behavior on accentColor { ColorAnimation { duration: 700 } }
    property bool playing: false
    property real length: 0
    property real basePos: 0
    property real stamp: 0
    property real pos: 0
    property real dragFrac: 0
    readonly property real frac: length > 0 ? Math.max(0, Math.min(1, pos / length)) : 0
    readonly property real shownFrac: seek.pressed ? dragFrac : frac

    property string cover: ""
    property int coverFront: 0
    property int textFront: 0
    property string curTitle: ""
    property string curArtist: ""

    function fmt(s) {
        s = Math.max(0, Math.floor(s))
        return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2)
    }

    function tick() {
        pos = playing ? Math.min(length > 0 ? length : 1e9, basePos + (Date.now() - stamp) / 1000) : basePos
    }

    readonly property real dim: host.style.dim

    function load(m) {
        accent = host.style.accent === "auto" ? m.accent : host.style.accent
        playing = m.playing
        length = m.length
        basePos = m.position
        stamp = m.stamp
        tick()
    }

    function setCover(url, animate) {
        if (url === cover) return
        cover = url
        const incoming = coverFront === 0 ? imgB : imgA
        incoming.source = url
        coverFront = 1 - coverFront
        if (animate && !host.style.reducedMotion) kenBurns.restart()
    }

    function swapText(title, artist, dir, animate) {
        const incoming = textFront === 0 ? tb1 : tb0
        const outgoing = textFront === 0 ? tb0 : tb1
        if (animate) outgoing.hide(dir)
        else outgoing.opacity = 0
        incoming.show(title, artist, dir, animate)
        textFront = 1 - textFront
        curTitle = title
        curArtist = artist
    }

    // A moment worth announcing: new song, skip, play/pause.
    function apply(m, kind, direction, animate) {
        const dir = direction === "prev" ? -1 : 1
        if (m.title !== curTitle || m.artist !== curArtist) swapText(m.title, m.artist, dir, animate)
        setCover(m.art, animate && (kind === "new" || kind === "next" || kind === "prev"))
        load(m)
        if (animate && !(hovered && host.style.hoverControls) && kind !== "new" && kind !== "") badge.play(kind)
    }

    // Quiet update: position jumped, the cover finally arrived, ...
    function refresh(m, animate) {
        if (m.title !== curTitle || m.artist !== curArtist) swapText(m.title, m.artist, 1, animate)
        setCover(m.art, false)
        load(m)
    }

    Timer {
        interval: 100
        repeat: true
        running: root.active && root.playing
        onTriggered: root.tick()
    }

    // -- cover -------------------------------------------------------------
    Item {
        id: coverBox
        anchors.fill: parent
        layer.enabled: true
        layer.effect: MultiEffect {
            saturation: root.playing ? 0.0 : -0.8
            brightness: root.playing ? 0.0 : -0.1
            Behavior on saturation { NumberAnimation { duration: 600 } }
            Behavior on brightness { NumberAnimation { duration: 600 } }
        }

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.darker(root.accentColor, 2.4) }
                GradientStop { position: 1.0; color: Qt.darker(root.accentColor, 5.0) }
            }
        }
        Icon {
            anchors.centerIn: parent
            name: "music"
            size: 92
            stroke: 1.4
            opacity: 0.15
            visible: root.cover === ""
        }
        Image {
            id: imgA
            anchors.fill: parent
            fillMode: Image.PreserveAspectCrop
            sourceSize: Qt.size(900, 900)
            smooth: true
            opacity: root.coverFront === 0 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 650; easing.type: Easing.InOutQuad } }
        }
        Image {
            id: imgB
            anchors.fill: parent
            fillMode: Image.PreserveAspectCrop
            sourceSize: Qt.size(900, 900)
            smooth: true
            opacity: root.coverFront === 1 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 650; easing.type: Easing.InOutQuad } }
        }
        NumberAnimation {
            id: kenBurns
            target: coverBox
            property: "scale"
            from: 1.14
            to: 1.0
            duration: 1600
            easing.type: Easing.OutCubic
        }
    }

    // -- scrims ------------------------------------------------------------
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.00; color: Qt.rgba(0, 0, 0, Math.min(1, 0.66 * root.dim)) }
            GradientStop { position: 0.38; color: Qt.rgba(0, 0, 0, Math.min(1, 0.20 * root.dim)) }
            GradientStop { position: 0.62; color: Qt.rgba(0, 0, 0, Math.min(1, 0.26 * root.dim)) }
            GradientStop { position: 1.00; color: Qt.rgba(0, 0, 0, Math.min(1, 0.70 * root.dim)) }
        }
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.20) }
            GradientStop { position: 0.85; color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.0) }
        }
    }
    Rectangle {
        anchors.fill: parent
        color: "black"
        opacity: root.hovered ? 0.34 : 0
        Behavior on opacity { NumberAnimation { duration: 260 } }
    }

    // -- title / artist ----------------------------------------------------
    Item {
        x: root.compact ? 22 : 26
        y: root.compact ? 14 : 24
        width: root.width - (root.compact ? 44 + 142 : 52 + 40)
        height: root.compact ? 50 : 64
        TextBlock { id: tb0; objectName: "tb0"; compact: root.compact; width: parent.width; height: parent.height }
        TextBlock { id: tb1; objectName: "tb1"; compact: root.compact; width: parent.width; height: parent.height }
    }

    // -- equaliser ---------------------------------------------------------
    Row {
        visible: host.style.equalizer
        opacity: root.compact && root.hovered && host.style.hoverControls ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 160 } }
        x: root.width - (root.compact ? 22 : 26) - width
        y: root.compact ? 18 : 28
        height: 26
        spacing: 3
        Repeater {
            model: [20, 26, 15, 23]
            delegate: Rectangle {
                id: bar
                required property int index
                required property int modelData
                property real h: 6
                width: 4
                radius: 2
                height: root.playing && !host.style.reducedMotion ? h : 5
                y: parent.height - height
                color: Qt.rgba(1, 1, 1, 0.94)
                Behavior on height { enabled: !root.playing; NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                SequentialAnimation on h {
                    running: root.playing && root.active && !host.style.reducedMotion
                    loops: Animation.Infinite
                    NumberAnimation { to: bar.modelData; duration: 380 + bar.index * 70; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 6 + bar.index; duration: 420 + bar.index * 55; easing.type: Easing.InOutSine }
                }
            }
        }
    }

    // -- progress ----------------------------------------------------------
    Item {
        id: prog
        visible: host.style.progress
        x: root.compact ? 22 : 26
        y: root.compact ? 58 : 98
        width: root.width - (root.compact ? 44 : 52)
        height: 22

        Rectangle {
            id: track
            width: parent.width
            height: 4
            radius: 2
            y: (parent.height - height) / 2
            color: Qt.rgba(1, 1, 1, 0.26)
        }
        Rectangle {
            id: fill
            height: 4
            radius: 2
            y: track.y
            width: Math.max(height, track.width * root.shownFrac)
            color: Qt.lighter(root.accentColor, 1.12)
        }
        Rectangle {
            id: knob
            width: 12
            height: 12
            radius: 6
            x: Math.min(track.width, fill.width) - width / 2
            y: (parent.height - height) / 2
            color: "white"
            scale: seek.pressed ? 1.55 : (root.hovered ? 1.25 : 1.0)
            Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack; easing.overshoot: 2.5 } }
            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowColor: root.accentColor
                shadowOpacity: 0.9
                shadowBlur: 0.8
            }
        }
        MouseArea {
            id: seek
            anchors.fill: parent
            anchors.margins: -6
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            function at(mx) { return Math.max(0, Math.min(1, (mx - 6) / track.width)) }
            onPressed: mouse => root.dragFrac = at(mouse.x)
            onPositionChanged: mouse => { if (pressed) root.dragFrac = at(mouse.x) }
            onReleased: host.seek(root.dragFrac)
        }
    }

    Txt {
        visible: host.style.progress
        x: root.compact ? 22 : 26
        y: root.compact ? 79 : 122
        text: root.fmt(seek.pressed ? root.dragFrac * root.length : root.pos)
        font.pixelSize: 13
        font.weight: Font.Medium
        color: Qt.rgba(1, 1, 1, 0.78)
    }
    Txt {
        visible: host.style.progress
        x: root.width - (root.compact ? 22 : 26) - width
        y: root.compact ? 79 : 122
        text: root.fmt(root.length)
        font.pixelSize: 13
        font.weight: Font.Medium
        color: Qt.rgba(1, 1, 1, 0.78)
    }

    // -- controls (hover) --------------------------------------------------
    // Compact: a small cluster at the right, beside the title. Full size: centred under the progress bar.
    Item {
        x: root.compact ? root.width - 22 - 125 : 78
        y: root.compact ? 14 : 146
        width: 56; height: 56
        scale: root.compact ? 0.68 : 1
        transformOrigin: Item.TopLeft
        CtlButton { icon: "skip-back"; show: root.hovered && host.style.hoverControls; delay: 0; onClicked: host.previous() }
    }
    Item {
        x: root.compact ? root.width - 22 - 125 + 42 : 170
        y: root.compact ? 13 : 144
        width: 60; height: 60
        scale: root.compact ? 0.68 : 1
        transformOrigin: Item.TopLeft
        PlayButton { playing: root.playing; show: root.hovered && host.style.hoverControls; delay: 60; onClicked: host.playPause() }
    }
    Item {
        x: root.compact ? root.width - 22 - 125 + 87 : 266
        y: root.compact ? 14 : 146
        width: 56; height: 56
        scale: root.compact ? 0.68 : 1
        transformOrigin: Item.TopLeft
        CtlButton { icon: "skip-forward"; show: root.hovered && host.style.hoverControls; delay: 120; onClicked: host.next() }
    }

    // -- event badge -------------------------------------------------------
    Item {
        id: badge
        property string icon: "play"
        property real nudge: 0
        width: 68
        height: 68
        x: (root.width - width) / 2
        y: root.compact ? (root.height - height) / 2 : 138
        opacity: 0
        scale: 0.5

        function play(kind) {
            icon = kind === "pause" ? "pause" : kind === "play" ? "play" : kind === "next" ? "skip-forward" : "skip-back"
            nudge = kind === "next" ? -18 : kind === "prev" ? 18 : 0
            anim.restart()
        }

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: Qt.rgba(0.05, 0.05, 0.07, 0.68)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.22)
        }
        Icon {
            anchors.centerIn: parent
            anchors.horizontalCenterOffset: badge.nudge + (badge.icon === "play" ? 2 : 0)
            name: badge.icon
            size: 30
            filled: true
            stroke: 1.5
        }

        SequentialAnimation {
            id: anim
            ParallelAnimation {
                NumberAnimation { target: badge; property: "opacity"; to: 1; duration: 150 }
                NumberAnimation { target: badge; property: "scale"; from: 0.55; to: 1; duration: 460; easing.type: Easing.OutBack; easing.overshoot: 2.6 }
                NumberAnimation { target: badge; property: "nudge"; to: 0; duration: 440; easing.type: Easing.OutCubic }
            }
            PauseAnimation { duration: 720 }
            ParallelAnimation {
                NumberAnimation { target: badge; property: "opacity"; to: 0; duration: 260; easing.type: Easing.InQuad }
                NumberAnimation { target: badge; property: "scale"; to: 1.25; duration: 260; easing.type: Easing.InQuad }
            }
        }
    }
}
