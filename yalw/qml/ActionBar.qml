import QtQuick

// Right-click on a card: a row of small actions laid over it.
Item {
    id: bar
    property bool open: false
    property string mode: "media"
    property string caption: ""
    readonly property bool onMedia: mode === "media" || mode === "lyrics"
    readonly property real size: height < 120 ? 34 : 42

    signal interacted()

    visible: opacity > 0.01
    opacity: open ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 160 } }
    onOpenChanged: caption = ""

    Rectangle { anchors.fill: parent; color: Qt.rgba(0.04, 0.04, 0.06, 0.82) }
    MouseArea { anchors.fill: parent; onClicked: bar.open = false }       // click anywhere else closes it

    // The five actions never change; only whether each one is shown does. (A list that is rebuilt
    // when the lyrics change would destroy the button that was just clicked, in the middle of its click.)
    readonly property var entries: [
        { id: "open", icon: "external-link" },
        { id: "earlier", icon: "chevrons-left" },
        { id: "later", icon: "chevrons-right" },
        { id: "wrong", icon: "ban" },
        { id: "silence", icon: "bell-off" }
    ]

    function shownFor(id) {
        switch (id) {
        case "open": return onMedia
        case "earlier":
        case "later": return onMedia && host.hasLyrics && !host.lyricsHidden
        case "wrong": return onMedia && (host.hasLyrics || host.lyricsHidden)
        default: return true
        }
    }

    function tip(id) {
        switch (id) {
        case "open": return host.labels.act_open
        case "earlier": return host.labels.act_earlier
        case "later": return host.labels.act_later
        case "wrong": return host.lyricsHidden ? host.labels.act_restore : host.labels.act_wrong
        default: return host.labels.act_silence
        }
    }

    function timing(offset) {
        caption = host.labels.act_timing + ": " + (offset > 0 ? "+" : "") + (Math.round(offset * 10) / 10).toFixed(1) + " s"
    }

    function act(id) {
        switch (id) {
        case "open": host.raisePlayer(); open = false; break
        case "earlier": host.nudgeLyrics(-0.5); timing(host.lyricsOffset); break
        case "later": host.nudgeLyrics(0.5); timing(host.lyricsOffset); break
        case "wrong": host.toggleSongLyrics(); open = false; break
        default: host.silence(); open = false
        }
        interacted()
    }

    Row {
        id: row
        objectName: "actionRow"
        anchors.horizontalCenter: parent.horizontalCenter
        y: (parent.height - bar.size) / 2 - 8
        spacing: 12
        Repeater {
            model: bar.entries
            delegate: Rectangle {
                id: btn
                required property var modelData
                objectName: "action-" + modelData.id
                visible: bar.shownFor(modelData.id)
                readonly property bool on: modelData.id === "wrong" && host.lyricsHidden
                width: bar.size; height: bar.size; radius: width / 2
                color: area.pressed ? Qt.rgba(1, 1, 1, 0.30) : area.containsMouse ? Qt.rgba(1, 1, 1, 0.20) : Qt.rgba(1, 1, 1, on ? 0.26 : 0.10)
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, on ? 0.55 : 0.16)
                scale: area.pressed ? 0.9 : area.containsMouse ? 1.08 : 1
                Behavior on color { ColorAnimation { duration: 120 } }
                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutBack } }
                Icon { anchors.centerIn: parent; name: btn.modelData.icon; size: bar.size * 0.46; stroke: 2 }
                MouseArea {
                    id: area
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onEntered: { bar.caption = bar.tip(btn.modelData.id); bar.interacted() }
                    onExited: bar.caption = ""
                    onClicked: bar.act(btn.modelData.id)
                }
            }
        }
    }
    Txt {
        x: 16
        width: parent.width - 32
        y: row.y + bar.size + 12
        horizontalAlignment: Text.AlignHCenter
        text: bar.caption
        font.pixelSize: 12
        font.weight: Font.Medium
        color: Qt.rgba(1, 1, 1, 0.78)
    }

    Timer { id: idle; interval: 5000; running: bar.open; repeat: false; onTriggered: bar.open = false }
    onInteracted: idle.restart()
}
