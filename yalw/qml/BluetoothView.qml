import QtQuick
import QtQuick.Effects

// "Device connected" pill: type icon, name, battery ring.
Item {
    id: root
    width: 372
    height: 88

    property string name: ""
    property string icon: "bluetooth"
    property int battery: -1
    property bool charging: false
    property bool connected: true
    property real level: 0
    readonly property bool hasBattery: battery >= 0 && host.style.btBattery
    property color tone: connected ? host.style.btAccent : "#6b7280"
    Behavior on tone { ColorAnimation { duration: 400 } }
    readonly property real preferredWidth: hasBattery ? 372 : 320

    property bool active: false

    function levelColor(p) { return p <= host.style.btLow ? "#ff5d6c" : p <= host.style.btWarn ? "#ffb347" : "#3ddc97" }
    property color gaugeColor: levelColor(battery)
    Behavior on gaugeColor { ColorAnimation { duration: 500 } }

    function fillTo(p, delay) {
        levelAnim.stop()
        levelAnim.delay = delay
        levelAnim.to = Math.max(0, p) / 100
        levelAnim.restart()
    }

    // A device just connected.
    function apply(b, animate) {
        name = b.name
        icon = b.icon
        charging = b.charging
        connected = b.connected
        gaugeColor = levelColor(b.battery)
        battery = b.battery
        level = 0
        fillTo(b.battery, 320)
        devIcon.scale = 0.4
        iconPop.restart()
    }

    // Battery reading changed while the card is up.
    function refresh(b) {
        charging = b.charging
        battery = b.battery
        fillTo(b.battery, 0)
    }

    SequentialAnimation {
        id: levelAnim
        property real delay: 0
        property real to: 0
        PauseAnimation { duration: levelAnim.delay }
        NumberAnimation { target: root; property: "level"; to: levelAnim.to; duration: 1000; easing.type: Easing.OutCubic }
    }
    SequentialAnimation {
        id: iconPop
        PauseAnimation { duration: 120 }
        NumberAnimation { target: devIcon; property: "scale"; to: 1; duration: 520; easing.type: Easing.OutBack; easing.overshoot: 3 }
    }

    // soft blue wash from the left + a hairline highlight on top
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: Qt.rgba(root.tone.r, root.tone.g, root.tone.b, 0.30) }
            GradientStop { position: 0.65; color: Qt.rgba(root.tone.r, root.tone.g, root.tone.b, 0.0) }
        }
    }
    Rectangle {
        width: parent.width
        height: 1
        color: Qt.rgba(1, 1, 1, 0.10)
    }

    // -- icon disc ---------------------------------------------------------
    Item {
        id: disc
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
            Rectangle {
                anchors.fill: parent
                radius: 28
                color: "transparent"
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.30)
            }
        }
        Icon {
            id: devIcon
            anchors.centerIn: parent
            name: root.icon
            size: 28
            stroke: 2
        }

        Rectangle {
            x: 38
            y: 38
            width: 22
            height: 22
            radius: 11
            color: "#0c0c0f"
            Icon {
                anchors.centerIn: parent
                name: root.connected ? "bluetooth-connected" : "bluetooth-off"
                size: 12
                tint: Qt.lighter(root.tone, 1.3)
                stroke: 2.4
            }
        }
    }

    // -- name + status -----------------------------------------------------
    Column {
        x: 88
        width: root.width - 88 - (root.hasBattery ? 88 : 24)
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4

        Txt {
            width: parent.width
            text: root.name
            font.pixelSize: 19
            font.weight: Font.Bold
            font.letterSpacing: -0.2
        }
        Txt {
            text: root.connected ? host.connectedLabel : host.disconnectedLabel
            font.pixelSize: 13
            font.weight: Font.Medium
            color: Qt.rgba(1, 1, 1, 0.64)
        }
    }

    // -- battery ring ------------------------------------------------------
    Item {
        id: gauge
        visible: root.hasBattery
        x: root.width - 18 - width
        y: (root.height - height) / 2
        width: 52
        height: 52

        Canvas {
            id: canvas
            anchors.fill: parent
            property real v: root.level
            property color col: root.gaugeColor
            onVChanged: requestPaint()
            onColChanged: requestPaint()
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                const c = width / 2
                const r = c - 4
                ctx.lineWidth = 5
                ctx.lineCap = "round"
                ctx.strokeStyle = "rgba(255,255,255,0.14)"
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
        Txt {
            anchors.centerIn: parent
            text: Math.round(root.level * 100)
            font.pixelSize: 16
            font.weight: Font.Bold
        }

        Rectangle {
            x: gauge.width - 15
            y: -7
            width: 22
            height: 22
            radius: 11
            color: "#0c0c0f"
            border.width: 1
            border.color: root.gaugeColor
            visible: root.charging
            SequentialAnimation on scale {
                running: root.charging && root.active
                loops: Animation.Infinite
                NumberAnimation { to: 1.18; duration: 650; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.0; duration: 650; easing.type: Easing.InOutSine }
            }
            Icon {
                anchors.centerIn: parent
                name: "zap"
                size: 12
                tint: root.gaugeColor
                filled: true
                stroke: 1.5
            }
        }
    }
}
