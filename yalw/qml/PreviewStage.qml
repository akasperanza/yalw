import QtQuick
import QtQuick.Effects

// A live copy of the card, drawn by the same views the widget uses, from the settings as they are right now.
Item {
    id: stage
    property string mode: "media"            // media | lyrics | bt | notice
    property bool switching: false            // a mode change is under way: let the box morph slowly
    property int device: 0
    property int sample: 0
    readonly property bool isMedia: mode === "media"
    readonly property bool isLyrics: mode === "lyrics"
    readonly property bool isBt: mode === "bt"
    readonly property bool isNotice: mode === "notice"
    readonly property bool calm: cfg.style.reducedMotion
    readonly property real fit: Math.max(0.3, Math.min(1, (panel.width - 40) / island.width, (panel.height - 80) / island.height))
    readonly property bool wordsOn: cfg.values.lyrics_words

    onModeChanged: {
        switching = true
        settle.restart()
        if (isBt) showDevice()
        if (isNotice) showNotice()
    }
    onWordsOnChanged: lyricsView.setLines(cfg.previewLyrics)

    function showNotice() { notice.apply(cfg.previewNotices[sample % cfg.previewNotices.length], true) }
    function showDevice() { bt.apply(cfg.previewDevices[device % cfg.previewDevices.length], true) }

    // the card shows the song that played last; `animate` lets a new one slide in
    function seed(animate) {
        media.refresh(cfg.freshMedia(30), animate)
        lyricsView.apply(cfg.previewLyrics, cfg.freshLyricsMedia())
    }
    Component.onCompleted: { seed(false); showDevice(); showNotice() }
    Connections { target: cfg; function onPreviewChanged() { stage.seed(true) } }
    Connections { target: cfg; function onStringsChanged() { stage.showNotice(); stage.seed(false) } }          // the samples are in the user's language

    Timer { id: settle; interval: 620; onTriggered: stage.switching = false }
    Timer { interval: Math.max(2000, cfg.previewLyricsLoop * 1000); repeat: true; running: stage.visible; onTriggered: stage.seed(false) }

    Rectangle {
        id: panel
        anchors.fill: parent
        anchors.leftMargin: 16; anchors.rightMargin: 16; anchors.topMargin: 4; anchors.bottomMargin: 8
        radius: 18
        color: cfg.pal.panel
        border.color: cfg.pal.line
        clip: true

        // a faint wash of the accent, so the stage belongs to the song that is playing
        Rectangle {
            anchors.fill: parent
            radius: panel.radius
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.alpha(cfg.pal.accent, 0.13) }
                GradientStop { position: 0.75; color: Qt.alpha(cfg.pal.accent, 0.0) }
            }
        }

        Item {
            id: field
            width: parent.width
            height: parent.height - 52

            Item {
                id: island
                anchors.centerIn: parent
                scale: stage.fit
                width: stage.isBt ? bt.preferredWidth : stage.isNotice ? notice.preferredWidth : cfg.style.cardW
                readonly property bool bare: stage.isNotice && notice.wordless
                height: stage.isMedia ? cfg.style.mediaH : stage.isLyrics ? cfg.style.lyricsH : bare ? notice.preferredHeight : 88
                property real radius: stage.isBt || stage.isNotice ? cfg.style.btRadius : cfg.style.mediaRadius
                Behavior on width { enabled: !stage.calm; NumberAnimation { duration: 540; easing.type: Easing.InOutCubic } }
                Behavior on height { enabled: !stage.calm; NumberAnimation { duration: 540; easing.type: Easing.InOutCubic } }
                Behavior on radius { NumberAnimation { duration: stage.switching && !stage.calm ? 540 : 90; easing.type: Easing.InOutCubic } }

                Rectangle { id: caster; anchors.fill: parent; radius: island.radius; color: "black"; visible: false }
                MultiEffect {
                    source: caster
                    anchors.fill: caster
                    visible: cfg.style.shadow && !island.bare
                    shadowEnabled: true
                    shadowColor: "black"
                    shadowOpacity: 0.55
                    shadowBlur: 1.0
                    shadowVerticalOffset: 14
                }
                Item {
                    anchors.fill: parent
                    layer.enabled: true
                    layer.effect: MultiEffect { maskEnabled: true; maskSource: maskItem; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0 }
                    Rectangle { anchors.fill: parent; color: "#0c0c0f"; opacity: island.bare ? 0 : 1; Behavior on opacity { NumberAnimation { duration: 200 } } }
                    MediaView {
                        id: media
                        hovered: hover.hovered
                        active: stage.visible
                        opacity: stage.isMedia ? 1 : 0
                        visible: opacity > 0.01
                        Behavior on opacity { NumberAnimation { duration: stage.calm ? 120 : 324; easing.type: Easing.InOutQuad } }
                    }
                    LyricsView {
                        id: lyricsView
                        hovered: hover.hovered
                        active: stage.visible && stage.isLyrics
                        opacity: stage.isLyrics ? 1 : 0
                        visible: opacity > 0.01
                        Behavior on opacity { NumberAnimation { duration: stage.calm ? 120 : 324; easing.type: Easing.InOutQuad } }
                    }
                    BluetoothView {
                        id: bt
                        active: stage.visible
                        width: parent.width
                        height: parent.height
                        opacity: stage.isBt ? 1 : 0
                        visible: opacity > 0.01
                        Behavior on opacity { NumberAnimation { duration: stage.calm ? 120 : 324; easing.type: Easing.InOutQuad } }
                    }
                    NoticeView {
                        id: notice
                        active: stage.visible
                        width: parent.width
                        height: parent.height
                        opacity: stage.isNotice ? 1 : 0
                        visible: opacity > 0.01
                        Behavior on opacity { NumberAnimation { duration: stage.calm ? 120 : 324; easing.type: Easing.InOutQuad } }
                    }
                }
                Item {
                    id: maskItem
                    anchors.fill: parent
                    visible: false
                    layer.enabled: true
                    Rectangle { anchors.fill: parent; radius: island.radius; color: "black" }
                }
                Rectangle { visible: !island.bare; anchors.fill: parent; radius: island.radius; color: "transparent"; border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.14) }

                HoverHandler { id: hover }
                TapHandler { enabled: stage.isBt || stage.isNotice; onTapped: { if (stage.isBt) { stage.device += 1; stage.showDevice() } else { stage.sample += 1; stage.showNotice() } } }   // try another one
            }
        }

        // which card to look at
        CfgSeg {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 14
            model: [{ value: "media", text: cfg.strings.preview_media }, { value: "lyrics", text: cfg.strings.preview_lyrics }, { value: "bt", text: cfg.strings.preview_bluetooth }, { value: "notice", text: cfg.strings.preview_notice }]
            current: stage.mode
            onPicked: v => stage.mode = v
        }
    }
}
