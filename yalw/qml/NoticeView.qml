import QtQuick
import QtQuick.Effects

// A small card for whatever an extension, a script or YALW itself wants to say: icon, title, subtitle,
// and (when it comes with a progress) a ring with a short value in it.
Item {
    id: root
    width: 372
    height: 88

    property string title: ""
    property string subtitle: ""
    property string icon: "bell"
    property string badge: ""
    property string key: ""
    property string valueText: ""
    property real progress: -1
    property real level: 0
    property bool active: false
    property color tone: host.style.btAccent
    Behavior on tone { ColorAnimation { duration: 400 } }
    readonly property bool hasRing: progress >= 0
    readonly property bool countsUp: hasRing && valueText === String(Math.round(progress * 100))   // the number follows the ring
    readonly property bool wordless: title === "" && subtitle === ""      // just the icon and the ring
    readonly property real preferredWidth: wordless ? 124 : hasRing ? 372 : 340
    readonly property real preferredHeight: wordless ? 124 : 88

    function fillTo(p, delay, ms) {
        levelAnim.stop()
        levelAnim.delay = delay
        levelAnim.ms = ms
        levelAnim.to = Math.max(0, p)
        levelAnim.restart()
    }

    // `n` is a sanitised notice (see yalw/notice.py). The same key again updates the card quietly.
    function apply(n, animate) {
        const same = animate && active && n.key !== "" && n.key === key
        title = n.title
        subtitle = n.subtitle
        icon = n.icon
        badge = n.badge
        key = n.key
        valueText = n.value
        progress = n.progress
        tone = n.accent !== "" ? n.accent : host.style.btAccent
        if (same) {
            fillTo(n.progress, 0, n.live ? 220 : 600)           // a value that keeps changing has to keep up with it
            return
        }
        level = 0
        fillTo(n.progress, n.live ? 80 : 320, n.live ? 650 : 1000)
        symbol.scale = 0.4
        iconPop.restart()
    }

    SequentialAnimation {
        id: levelAnim
        property real delay: 0
        property real to: 0
        property int ms: 1000
        PauseAnimation { duration: levelAnim.delay }
        NumberAnimation { target: root; property: "level"; to: levelAnim.to; duration: levelAnim.ms; easing.type: Easing.OutCubic }
    }
    SequentialAnimation {
        id: iconPop
        PauseAnimation { duration: 120 }
        NumberAnimation { target: symbol; property: "scale"; to: 1; duration: 520; easing.type: Easing.OutBack; easing.overshoot: 3 }
    }

    Rectangle {
        visible: !root.wordless
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: Qt.rgba(root.tone.r, root.tone.g, root.tone.b, 0.30) }
            GradientStop { position: 0.65; color: Qt.rgba(root.tone.r, root.tone.g, root.tone.b, 0.0) }
        }
    }
    Rectangle { visible: !root.wordless; width: parent.width; height: 1; color: Qt.rgba(1, 1, 1, 0.10) }

    // -- icon disc ---------------------------------------------------------
    Item {
        visible: !root.wordless
        x: 16
        y: 16
        width: 56
        height: 56

        Rectangle {
            anchors.fill: parent
            radius: 28
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.lighter(root.tone, 1.3) }
                GradientStop { position: 1.0; color: Qt.darker(root.tone, 1.35) }
            }
            Rectangle { anchors.fill: parent; radius: 28; color: "transparent"; border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.30) }
        }
        Icon { id: symbol; anchors.centerIn: parent; name: root.icon; size: 28; stroke: 2 }

        Rectangle {                                  // without a ring the badge sits on the disc
            visible: root.badge !== "" && !root.hasRing
            x: 38; y: 38; width: 22; height: 22; radius: 11
            color: "#0c0c0f"
            Icon { anchors.centerIn: parent; name: root.badge; size: 12; tint: Qt.lighter(root.tone, 1.3); stroke: 2.4 }
        }
    }

    // -- words -------------------------------------------------------------
    Column {
        visible: !root.wordless
        x: 88
        width: root.width - 88 - (root.hasRing ? 88 : 24)
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4
        Txt { width: parent.width; text: root.title; font.pixelSize: 19; font.weight: Font.Bold; font.letterSpacing: -0.2 }
        Txt {
            visible: root.subtitle !== ""
            width: parent.width
            text: root.subtitle
            font.pixelSize: 13
            font.weight: Font.Medium
            color: Qt.rgba(1, 1, 1, 0.64)
        }
    }

    // -- ring --------------------------------------------------------------
    Item {
        id: gauge
        visible: root.hasRing
        x: root.wordless ? (root.width - width) / 2 : root.width - 18 - width
        y: (root.height - height) / 2
        width: root.wordless ? 104 : 52
        height: width
        layer.enabled: root.wordless                 // nothing behind it, so it carries its own soft shadow
        layer.effect: MultiEffect { shadowEnabled: true; shadowColor: "#000000"; shadowOpacity: 0.55; shadowBlur: 0.7; shadowVerticalOffset: 3 }

        Canvas {
            anchors.fill: parent
            property real v: root.level
            property color col: root.tone
            onVChanged: requestPaint()
            onColChanged: requestPaint()
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                const c = width / 2
                const r = c - width * 0.08
                ctx.lineWidth = width * 0.096
                ctx.lineCap = "round"
                ctx.strokeStyle = root.wordless ? "rgba(255,255,255,0.22)" : "rgba(255,255,255,0.14)"
                ctx.beginPath()
                ctx.arc(c, c, r, 0, Math.PI * 2)
                ctx.stroke()
                if (v > 0.004) {
                    ctx.strokeStyle = col
                    ctx.beginPath()
                    ctx.arc(c, c, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * v)
                    ctx.stroke()
                }
            }
        }
        Icon { visible: root.wordless; x: (parent.width - width) / 2; y: parent.height * 0.17; name: root.icon; size: 24; stroke: 2.2 }   // the charge icon above the number
        Txt {
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.wordless ? parent.height * 0.42 : (parent.height - height) / 2
            text: root.countsUp ? Math.round(root.level * 100) : root.valueText
            font.pixelSize: root.wordless ? 32 : root.valueText.length > 3 ? 13 : 16
            font.weight: Font.Bold
        }

        Rectangle {
            visible: root.badge !== ""
            x: gauge.width - 15; y: -7; width: 22; height: 22; radius: 11
            color: "#0c0c0f"
            border.width: 1
            border.color: root.tone
            SequentialAnimation on scale {
                running: root.badge !== "" && root.active
                loops: Animation.Infinite
                NumberAnimation { to: 1.18; duration: 650; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.0; duration: 650; easing.type: Easing.InOutSine }
            }
            Icon { anchors.centerIn: parent; name: root.badge; size: 12; tint: root.tone; filled: true; stroke: 1.5 }
        }
    }
}
