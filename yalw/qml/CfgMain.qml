import QtQuick
import QtQuick.Controls
import QtQuick.Window
import QtQuick.Layouts

Window {
    id: win
    width: 560
    height: 780
    minimumWidth: 500
    minimumHeight: 520
    visible: true
    title: cfg.strings.app_title
    color: cfg.pal.bg

    property int tab: 0
    readonly property var pal: cfg.pal
    readonly property var tr: cfg.strings
    readonly property var vals: cfg.values
    readonly property var specs: cfg.specs
    readonly property var tabNames: ["tab_general", "tab_appearance", "tab_events", "tab_bluetooth", "tab_lyrics", "tab_extensions", "tab_status"]

    function uptime(s) {
        s = Math.floor(s)
        return s < 60 ? s + " s" : s < 3600 ? Math.floor(s / 60) + " min" : Math.floor(s / 3600) + " h " + Math.floor((s % 3600) / 60) + " min"
    }
    function lim(attr, which) { return specs[attr][which] }

    // the preview shows what the open page is about
    onTabChanged: stage.mode = tab === 3 ? "bt" : tab === 4 ? "lyrics" : tab === 5 ? "notice" : "media"

    // -- header ------------------------------------------------------------
    Item {
        id: header
        anchors.top: parent.top
        width: parent.width
        height: 52
        Row {
            x: 20
            anchors.verticalCenter: parent.verticalCenter
            spacing: 7
            Txt { text: "YALW"; font.pixelSize: 17; font.weight: Font.Bold; font.letterSpacing: 1.2; color: win.pal.text; anchors.verticalCenter: parent.verticalCenter }
            Txt { text: "Config"; font.pixelSize: 17; font.weight: Font.Normal; color: win.pal.dim; anchors.verticalCenter: parent.verticalCenter }
        }
        Item {
            id: state
            anchors.right: langRow.left
            anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            width: stateRow.width
            height: 26
            visible: cfg.daemon.checked
            Row {
                id: stateRow
                anchors.verticalCenter: parent.verticalCenter
                spacing: 7
                Rectangle {
                    width: 7; height: 7; radius: 3.5; anchors.verticalCenter: parent.verticalCenter
                    color: cfg.daemon.running ? win.pal.ok : win.pal.warn
                    SequentialAnimation on opacity {
                        running: cfg.daemon.running && win.visible
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.4; duration: 1100; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1.0; duration: 1100; easing.type: Easing.InOutSine }
                    }
                }
                Txt { text: cfg.daemon.running ? win.tr.st_running : win.tr.st_stopped; font.pixelSize: 12; color: stateArea.containsMouse ? win.pal.text : win.pal.muted; anchors.verticalCenter: parent.verticalCenter }
            }
            MouseArea { id: stateArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: win.tab = 6 }
        }
        Row {
            id: langRow
            anchors.right: parent.right
            anchors.rightMargin: 20
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            Icon { name: "languages"; size: 15; tint: win.pal.dim; anchors.verticalCenter: parent.verticalCenter }
            CfgDrop {
                popupWidth: 150
                model: cfg.languages
                current: vals.language
                onPicked: v => cfg.set("language", v)
            }
        }
    }

    // -- live preview ------------------------------------------------------
    PreviewStage {
        id: stage
        anchors.top: header.bottom
        width: parent.width
        readonly property real room: win.height - 470
        height: win.tab === 6 || room < 190 ? 0 : Math.min(300, room)
        visible: height > 1
        clip: true
        Behavior on height { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    }

    // -- tabs --------------------------------------------------------------
    Item {
        id: tabs
        anchors.top: stage.bottom
        anchors.topMargin: 4
        width: parent.width
        height: 42
        readonly property real cell: (width - 24) / win.tabNames.length
        Row {
            x: 12
            Repeater {
                model: win.tabNames
                delegate: CfgTab {
                    required property string modelData
                    required property int index
                    width: tabs.cell
                    text: win.tr[modelData]
                    on: win.tab === index
                    onClicked: win.tab = index
                }
            }
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: win.pal.line }
        Rectangle {
            anchors.bottom: parent.bottom
            height: 3; radius: 1.5
            width: 26
            x: 12 + win.tab * tabs.cell + (tabs.cell - width) / 2
            color: win.pal.accent
            Behavior on x { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
        }
    }

    // -- pages -------------------------------------------------------------
    StackLayout {
        anchors.top: tabs.bottom
        anchors.bottom: footer.top
        anchors.left: parent.left
        anchors.right: parent.right
        currentIndex: win.tab

        // General
        ScrollView {
            id: p0
            contentWidth: availableWidth
            clip: true
            Column {
                x: 16; width: p0.availableWidth - 32
                topPadding: 12; bottomPadding: 8
                CfgSection {
                    title: win.tr.g_where
                    CfgRow { label: win.tr.position; CfgPos { current: vals.position; onPicked: v => cfg.set("position", v) } }
                    CfgRow {
                        label: win.tr.margin; desc: win.tr.d_margin
                        CfgSlider { from: win.lim("margin", "lo"); to: 200; step: 2; value: vals.margin; suffix: " px"; onMoved: v => cfg.set("margin", v) }
                    }
                    CfgRow {
                        label: win.tr.monitor; desc: win.tr.d_monitor
                        CfgDrop {
                            model: [{ value: "", text: win.tr.monitor_primary }].concat(cfg.monitors.map(m => ({ value: m, text: m })))
                            current: vals.monitor
                            onPicked: v => cfg.set("monitor", v)
                        }
                    }
                    CfgRow {
                        label: win.tr.backend; desc: win.tr.d_backend
                        CfgDrop {
                            popupWidth: 230
                            model: [
                                { value: "auto", text: win.tr.backend_auto },
                                { value: "layer-shell", text: "Wayland overlay (layer-shell)" },
                                { value: "xcb", text: "X11 / XWayland" },
                                { value: "wayland", text: "Wayland window" }]
                            current: vals.backend
                            onPicked: v => cfg.set("backend", v)
                        }
                    }
                }
            }
        }

        // Appearance
        ScrollView {
            id: p1
            contentWidth: availableWidth
            clip: true
            Column {
                x: 16; width: p1.availableWidth - 32
                topPadding: 12; bottomPadding: 8
                CfgSection {
                    title: win.tr.g_card
                    CfgRow { label: win.tr.compact; desc: win.tr.d_compact; CfgToggle { checked: vals.compact; onToggled: v => cfg.set("compact", v) } }
                    CfgRow {
                        label: win.tr.scale; desc: win.tr.d_scale
                        CfgSlider { from: win.lim("scale", "lo"); to: win.lim("scale", "hi"); step: 0.05; value: vals.scale; factor: 100; suffix: "%"; onMoved: v => cfg.set("scale", v) }
                    }
                    CfgRow {
                        label: win.tr.media_radius
                        CfgSlider { from: 0; to: 44; step: 1; value: vals.media_radius; onMoved: v => cfg.set("media_radius", v) }
                    }
                    CfgRow {
                        label: win.tr.bluetooth_radius
                        CfgSlider { from: 0; to: 44; step: 1; value: vals.bluetooth_radius; onMoved: v => cfg.set("bluetooth_radius", v) }
                    }
                    CfgRow {
                        label: win.tr.dim; desc: win.tr.d_dim
                        CfgSlider { from: 0; to: win.lim("dim", "hi"); step: 0.05; value: vals.dim; factor: 100; suffix: "%"; onMoved: v => cfg.set("dim", v) }
                    }
                    CfgRow {
                        label: win.tr.accent; desc: win.tr.d_accent
                        CfgSeg {
                            model: [{ value: "auto", text: win.tr.accent_auto }, { value: "fixed", text: win.tr.accent_fixed }]
                            current: vals.accent === "auto" ? "auto" : "fixed"
                            onPicked: v => cfg.set("accent", v === "auto" ? "auto" : "#e5484d")
                        }
                    }
                    CfgRow {
                        visible: vals.accent !== "auto"
                        label: ""
                        CfgColor { color: vals.accent === "auto" ? "#e5484d" : vals.accent; onPicked: h => cfg.set("accent", h) }
                    }
                    CfgRow {
                        label: win.tr.bluetooth_accent; desc: win.tr.d_bluetooth_accent
                        CfgColor { color: vals.bluetooth_accent; onPicked: h => cfg.set("bluetooth_accent", h) }
                    }
                }
                CfgSection {
                    title: win.tr.g_effects
                    CfgRow { label: win.tr.shadow; desc: win.tr.d_shadow; CfgToggle { checked: vals.shadow; onToggled: v => cfg.set("shadow", v) } }
                    CfgRow { label: win.tr.equalizer; desc: win.tr.d_equalizer; CfgToggle { checked: vals.equalizer; onToggled: v => cfg.set("equalizer", v) } }
                    CfgRow { label: win.tr.progress; desc: win.tr.d_progress; CfgToggle { checked: vals.show_progress; onToggled: v => cfg.set("show_progress", v) } }
                    CfgRow { label: win.tr.hover_controls; desc: win.tr.d_hover_controls; CfgToggle { checked: vals.hover_controls; onToggled: v => cfg.set("hover_controls", v) } }
                    CfgRow { label: win.tr.reduced_motion; desc: win.tr.d_reduced_motion; CfgToggle { checked: vals.reduced_motion; onToggled: v => cfg.set("reduced_motion", v) } }
                    CfgRow {
                        label: win.tr.font
                        CfgDrop {
                            popupWidth: 230
                            model: cfg.fonts.map(f => f.value === "" ? { value: "", text: win.tr.font_auto } : f)
                            current: vals.font
                            onPicked: v => cfg.set("font", v)
                        }
                    }
                }
            }
        }

        // Events
        ScrollView {
            id: p2
            contentWidth: availableWidth
            clip: true
            Column {
                x: 16; width: p2.availableWidth - 32
                topPadding: 12; bottomPadding: 8
                CfgSection {
                    title: win.tr.g_show
                    CfgRow { label: win.tr.ev_new_track; desc: win.tr.d_new_track; CfgToggle { checked: vals.new_track; onToggled: v => cfg.set("new_track", v) } }
                    CfgRow { label: win.tr.ev_skip; desc: win.tr.d_skip; CfgToggle { checked: vals.skip; onToggled: v => cfg.set("skip", v) } }
                    CfgRow { label: win.tr.ev_play_pause; desc: win.tr.d_play_pause; CfgToggle { checked: vals.play_pause; onToggled: v => cfg.set("play_pause", v) } }
                    CfgRow { label: win.tr.ev_bluetooth; desc: win.tr.d_ev_bluetooth; CfgToggle { checked: vals.bluetooth; onToggled: v => cfg.set("bluetooth", v) } }
                    CfgRow { label: win.tr.ev_bluetooth_disconnect; desc: win.tr.d_ev_bluetooth_disconnect; CfgToggle { checked: vals.bluetooth_disconnect; onToggled: v => cfg.set("bluetooth_disconnect", v) } }
                    CfgRow { label: win.tr.ev_power_plugged; desc: win.tr.d_power_plugged; CfgToggle { checked: vals.power_plugged; onToggled: v => cfg.set("power_plugged", v) } }
                    CfgRow { label: win.tr.ev_power_unplugged; desc: win.tr.d_power_unplugged; CfgToggle { checked: vals.power_unplugged; onToggled: v => cfg.set("power_unplugged", v) } }
                }
                CfgSection {
                    title: win.tr.g_when
                    CfgRow {
                        label: win.tr.t_media; desc: win.tr.d_t_media
                        CfgSlider { from: 1; to: 15; step: 0.5; value: vals.media_seconds; suffix: " " + win.tr.seconds; onMoved: v => cfg.set("media_seconds", v) }
                    }
                    CfgRow {
                        label: win.tr.t_bluetooth; desc: win.tr.d_t_bluetooth
                        CfgSlider { from: 1; to: 15; step: 0.5; value: vals.bluetooth_seconds; suffix: " " + win.tr.seconds; onMoved: v => cfg.set("bluetooth_seconds", v) }
                    }
                    CfgRow {
                        label: win.tr.t_notice; desc: win.tr.d_t_notice
                        CfgSlider { from: 1; to: 15; step: 0.5; value: vals.notice_seconds; suffix: " " + win.tr.seconds; onMoved: v => cfg.set("notice_seconds", v) }
                    }
                }
                CfgSection {
                    title: win.tr.g_players
                    CfgRow {
                        label: win.tr.ignore_players; desc: win.tr.d_ignore_players
                        CfgField { width: 200; text: vals.ignore_players.join(", "); placeholder: win.tr.ignore_hint; onEdited: t => cfg.set("ignore_players", t) }
                    }
                }
            }
        }

        // Bluetooth
        ScrollView {
            id: p3
            contentWidth: availableWidth
            clip: true
            Column {
                x: 16; width: p3.availableWidth - 32
                topPadding: 12; bottomPadding: 8
                CfgSection {
                    title: win.tr.g_card
                    CfgRow { label: win.tr.show_battery; desc: win.tr.d_show_battery; CfgToggle { checked: vals.show_battery; onToggled: v => cfg.set("show_battery", v) } }
                    CfgRow {
                        label: win.tr.battery_low; desc: win.tr.d_battery_low
                        CfgSlider { from: 1; to: 50; step: 1; value: vals.battery_low; suffix: "%"; onMoved: v => cfg.set("battery_low", v) }
                    }
                    CfgRow {
                        label: win.tr.battery_warn; desc: win.tr.d_battery_warn
                        CfgSlider { from: 2; to: 80; step: 1; value: vals.battery_warn; suffix: "%"; onMoved: v => cfg.set("battery_warn", v) }
                    }
                }
            }
        }

        // Lyrics
        ScrollView {
            id: p4
            contentWidth: availableWidth
            clip: true
            Column {
                x: 16; width: p4.availableWidth - 32
                topPadding: 12; bottomPadding: 8
                CfgSection {
                    title: win.tr.g_lyrics
                    CfgRow { label: win.tr.lyr_enable; desc: win.tr.d_lyr_enable; CfgToggle { checked: vals.lyrics_enabled; onToggled: v => cfg.set("lyrics_enabled", v) } }
                    CfgRow {
                        label: win.tr.lyr_when; desc: win.tr.d_lyr_when
                        CfgSeg {
                            model: [{ value: "chorus", text: win.tr.lyr_chorus }, { value: "always", text: win.tr.lyr_always }]
                            current: vals.lyrics_when
                            onPicked: v => cfg.set("lyrics_when", v)
                        }
                    }
                    CfgRow { label: win.tr.lyr_words; desc: win.tr.d_lyr_words; CfgToggle { checked: vals.lyrics_words; onToggled: v => cfg.set("lyrics_words", v) } }
                }
                CfgSection {
                    visible: vals.lyrics_when === "chorus"
                    title: win.tr.g_experimental
                    CfgRow { label: win.tr.lyr_guess; desc: win.tr.d_lyr_guess; CfgToggle { checked: vals.lyrics_guess; onToggled: v => cfg.set("lyrics_guess", v) } }
                    CfgRow {
                        opacity: vals.lyrics_guess ? 1 : 0.45
                        label: win.tr.lyr_learn; desc: win.tr.d_lyr_learn
                        CfgToggle { enabled: vals.lyrics_guess; checked: vals.lyrics_learn; onToggled: v => cfg.set("lyrics_learn", v) }
                    }
                    CfgNote { opacity: vals.lyrics_guess ? 1 : 0.45; text: win.tr.lyr_learn_info }
                    CfgRow {
                        label: win.tr.lyr_forget + "  ·  " + cfg.learned
                        CfgButton { text: win.tr.lyr_forget_btn; enabled: cfg.learned > 0; onClicked: cfg.forgetLearned() }
                    }
                }
                CfgSection {
                    title: win.tr.g_sources
                    CfgRow { label: win.tr.lyr_local; CfgToggle { checked: vals.lyrics_local; onToggled: v => cfg.set("lyrics_local", v) } }
                    CfgRow { label: win.tr.lyr_apple; CfgToggle { checked: vals.lyrics_apple; onToggled: v => cfg.set("lyrics_apple", v) } }
                    CfgRow { label: win.tr.lyr_lrclib; CfgToggle { checked: vals.lyrics_lrclib; onToggled: v => cfg.set("lyrics_lrclib", v) } }
                    CfgRow { label: win.tr.lyr_boidu; CfgToggle { checked: vals.lyrics_boidu; onToggled: v => cfg.set("lyrics_boidu", v) } }
                    CfgNote { text: win.tr.lyr_privacy }
                }
            }
        }

        // Extensions
        ScrollView {
            id: p5
            contentWidth: availableWidth
            clip: true
            function stateText(m) {
                if (!m.compatible) return win.tr.ext_s_incompatible
                if (!m.enabled) return ""
                const key = { running: "ext_s_running", crashed: "ext_s_crashed", failed: "ext_s_failed", stopped: "ext_s_stopped" }[m.state]
                return (key ? win.tr[key] : win.tr.ext_s_wait) + (m.error ? ": " + m.error : "")
            }
            Column {
                x: 16; width: p5.availableWidth - 32
                topPadding: 12; bottomPadding: 8
                CfgSection {
                    title: win.tr.g_extensions
                    CfgNote { text: win.tr.ext_warning }
                    CfgRow { visible: cfg.extensionList.length === 0; label: win.tr.ext_none }
                    Repeater {
                        model: cfg.extensionList
                        delegate: CfgRow {
                            required property var modelData
                            readonly property string note: p5.stateText(modelData)
                            label: modelData.name + (modelData.version ? "  " + modelData.version : "")
                            desc: modelData.description + (modelData.author ? (modelData.description ? "  ·  " : "") + modelData.author : "") + (note ? "\n" + note : "")
                            CfgToggle { enabled: modelData.compatible; opacity: modelData.compatible ? 1 : 0.4; checked: modelData.enabled; onToggled: v => cfg.setExtension(modelData.id, v) }
                        }
                    }
                    CfgRow {
                        label: win.tr.ext_folder; desc: cfg.extensionsPath
                        Row {
                            spacing: 6
                            CfgButton { icon: "refresh-cw"; text: win.tr.ext_rescan; onClicked: cfg.rescanExtensions() }
                            CfgButton { icon: "external-link"; text: win.tr.ext_open; onClicked: cfg.openExtensionsFolder() }
                        }
                    }
                }
            }
        }

        // Status
        ScrollView {
            id: p6
            contentWidth: availableWidth
            clip: true
            onVisibleChanged: if (visible) cfg.refreshLog()
            Timer { interval: 2500; repeat: true; running: p6.visible && win.visible; onTriggered: cfg.refreshLog() }
            readonly property var info: cfg.daemon.info
            readonly property var lyr: info.lyrics ? info.lyrics : ({})
            Column {
                x: 16; width: p6.availableWidth - 32
                topPadding: 12; bottomPadding: 8

                CfgSection {
                    title: win.tr.tab_status
                    CfgRow {
                        label: cfg.daemon.running ? win.tr.st_running + (p6.info.version ? "  ·  v" + p6.info.version : "") : win.tr.st_stopped
                        CfgButton { text: cfg.daemon.running ? win.tr.stat_restart : win.tr.stat_start; onClicked: cfg.startOrRestart() }
                    }
                    CfgNote { visible: cfg.daemon.outdated === true; tone: win.pal.warn; text: win.tr.stat_outdated }
                    CfgRow { visible: !!p6.info.backend; label: win.tr.backend; Txt { text: p6.info.backend || ""; font.pixelSize: 13; color: win.pal.muted } }
                    CfgRow { visible: p6.info.uptime !== undefined; label: win.tr.stat_uptime; Txt { text: win.uptime(p6.info.uptime || 0); font.pixelSize: 13; color: win.pal.muted } }
                    CfgRow {
                        visible: !!p6.info.song
                        label: win.tr.stat_song
                        Txt {
                            width: 250; horizontalAlignment: Text.AlignRight
                            text: p6.info.song && p6.info.song.title ? p6.info.song.artist + "  ·  " + p6.info.song.title : win.tr.stat_nothing
                            font.pixelSize: 13; color: win.pal.muted
                        }
                    }
                    CfgRow { visible: p6.info.players !== undefined; label: win.tr.stat_players; Txt { text: String(p6.info.players); font.pixelSize: 13; color: win.pal.muted } }
                    CfgRow {
                        visible: p6.info.bluetooth !== undefined
                        label: win.tr.tab_bluetooth
                        Txt { text: p6.info.bluetooth ? win.tr.src_ok : win.tr.stat_bt_off; font.pixelSize: 13; color: p6.info.bluetooth ? win.pal.ok : win.pal.warn }
                    }
                    CfgRow {
                        visible: cfg.daemon.running
                        label: win.tr.act_silence
                        CfgToggle { checked: !!p6.info.quiet; onToggled: v => cfg.setQuiet(v) }
                    }
                }

                CfgSection {
                    visible: cfg.daemon.running
                    title: win.tr.g_lyrics
                    CfgRow {
                        label: win.tr.g_lyrics
                        Txt {
                            width: 260; horizontalAlignment: Text.AlignRight
                            text: !p6.lyr.enabled ? win.tr.stat_off
                                : p6.lyr.hidden ? win.tr.stat_hidden
                                : p6.lyr.found ? p6.lyr.source + "  ·  " + (p6.lyr.fallback ? win.tr.stat_whole : p6.lyr.windows + " " + win.tr.stat_windows) + (p6.lyr.offset ? "  ·  " + (p6.lyr.offset > 0 ? "+" : "") + p6.lyr.offset.toFixed(1) + " s" : "")
                                : win.tr.stat_none
                            font.pixelSize: 13; color: win.pal.muted
                        }
                    }
                    CfgNote { visible: !!p6.lyr.match; text: win.tr.stat_matched + ": " + (p6.lyr.match || "") }
                    CfgRow {
                        visible: !!p6.info.audio && !!p6.lyr.enabled
                        label: win.tr.stat_audio
                        Txt {
                            width: 260; horizontalAlignment: Text.AlignRight
                            text: !p6.info.audio || !p6.info.audio.enabled ? win.tr.aud_off
                                : p6.info.audio.state === "listening" ? win.tr.aud_listening
                                : p6.info.audio.state === "learned" ? win.tr.aud_done
                                : p6.info.audio.state === "unavailable" ? win.tr.aud_unavail
                                : win.tr.aud_idle
                            font.pixelSize: 13; color: win.pal.muted
                        }
                    }
                    Repeater {
                        model: p6.lyr.enabled ? p6.lyr.sources.filter(n => n !== "local") : []
                        delegate: CfgRow {
                            required property string modelData
                            readonly property var h: p6.lyr.health && p6.lyr.health[modelData] ? p6.lyr.health[modelData] : null
                            label: ({ apple: "Apple Music (lrc.red)", lrclib: "LRCLIB", boidu: "boidu" })[modelData]
                            Row {
                                spacing: 7
                                Rectangle { width: 7; height: 7; radius: 3.5; anchors.verticalCenter: parent.verticalCenter; color: !h ? win.pal.dim : h.last === "ok" ? win.pal.ok : win.pal.warn }
                                Txt { text: !h ? win.tr.src_idle : h.last === "ok" ? win.tr.src_ok : win.tr.src_fail + (h.error ? "  ·  " + h.error : ""); font.pixelSize: 12; color: win.pal.muted; elide: Text.ElideRight; width: Math.min(implicitWidth, 230) }
                            }
                        }
                    }
                }

                CfgSection {
                    title: win.tr.stat_log
                    Item {
                        width: parent.width; height: 244
                        Rectangle {
                            anchors.fill: parent; anchors.topMargin: 14; anchors.bottomMargin: 8
                            radius: 10; color: win.pal.bg; border.color: win.pal.line
                            Flickable {
                                id: logFlick
                                anchors.fill: parent; anchors.margins: 10
                                contentWidth: logText.paintedWidth; contentHeight: logText.paintedHeight
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                TextEdit {
                                    id: logText
                                    readOnly: true; selectByMouse: true
                                    text: cfg.log !== "" ? cfg.log : win.tr.stat_nolog
                                    color: win.pal.muted; font.family: "monospace"; font.pixelSize: 11
                                    wrapMode: TextEdit.NoWrap
                                    onTextChanged: Qt.callLater(() => logFlick.contentY = Math.max(0, logFlick.contentHeight - logFlick.height))
                                }
                            }
                        }
                    }
                    CfgRow { label: ""; CfgButton { icon: "copy"; text: win.tr.stat_copy; onClicked: cfg.copyLog() } }
                }
            }
        }
    }

    // -- footer ------------------------------------------------------------
    Item {
        id: footer
        anchors.bottom: parent.bottom
        width: parent.width
        height: 46
        Rectangle { width: parent.width; height: 1; color: win.pal.line }

        Row {
            x: 20
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            Rectangle {
                width: 7; height: 7; radius: 3.5
                anchors.verticalCenter: parent.verticalCenter
                color: cfg.dirty ? win.pal.warn : win.pal.ok
                visible: cfg.dirty || cfg.status !== ""
            }
            Txt {
                text: cfg.dirty ? win.tr.st_saving : cfg.status
                font.pixelSize: 12
                color: win.pal.muted
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        CfgButton {
            id: resetButton
            property bool armed: false
            anchors.right: parent.right
            anchors.rightMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            quiet: true
            icon: "rotate-ccw"
            text: armed ? win.tr.reset_confirm : win.tr.reset
            onClicked: { if (armed) { armed = false; cfg.reset() } else { armed = true; disarm.restart() } }
            Timer { id: disarm; interval: 3000; onTriggered: resetButton.armed = false }
        }
    }
}
