import QtQuick
import QtQuick.Window
import QtQuick.Effects

// One floating "island" that morphs between the media card and the Bluetooth pill.
Window {
    id: win
    title: "YALW"
    width: host.stageW
    height: host.stageH
    color: "transparent"
    visible: false

    property string mode: "media"      // "media" | "lyrics" | "bluetooth" | "notice"
    property bool shown: false
    property bool forceHover: false    // used by `yalw snapshot`
    readonly property bool hovered: hover.hovered || forceHover
    readonly property bool holdOpen: actions.open     // the action bar is up: do not take the card away
    property double holdUntil: 0       // a card that came up stays at least until then, whatever asks it to go
    property string pendingClose: ""   // a close that is waiting for that time ("time" | "end")
    property bool probing: false       // just mapped, still invisible: is the pointer where the card would be?
    property string liveKey: ""        // the card on screen is this live card (it stays until cleared or dismissed)
    property bool lone: false          // what is on screen (or about to be) is the lone charging ring
    property double mappedAt: 0
    property double probeSeen: 0       // when the pointer last reported itself over the (invisible) card
    onHoveredChanged: armTimer()
    onHoldOpenChanged: armTimer()

    // -- show / hide -------------------------------------------------------
    function armTimer() {
        if (!shown) { idleTimer.stop(); return }
        if (mode === "notice" && liveKey !== "") { hideTimer.stop(); idleTimer.stop(); return }       // a live card only goes when told to
        // Held open (hovered, action bar up, or the lyrics card, which stays for the chorus): the card still goes
        // when nothing moves for a few seconds. Otherwise it simply lives out its own time.
        // A lyrics card nobody is touching is a card in the middle of its chorus: only the chorus ends it (a held note
        // or a pause between lines is not "nothing happening"), so it never blinks out and back in.
        if (mode === "lyrics" && !hovered && !holdOpen) { hideTimer.stop(); idleTimer.stop(); return }
        if (mode === "lyrics" || hovered || holdOpen) { hideTimer.stop(); idleTimer.restart(); return }
        idleTimer.stop()
        hideTimer.restart()
    }

    // Anything happening on the card (the pointer moving or clicking, a new lyric line, a lit word) is movement.
    function touch() { if (idleTimer.running) idleTimer.restart() }

    function idle() {
        if (mode === "lyrics") host.lyricsIdled()                  // it returns with the next line
        dismiss()
    }

    function present(newMode) {
        if (newMode !== "notice") liveKey = ""
        exitAnim.stop()
        fastExit.stop()
        island.kill = 0
        holdTimer.stop()                                   // a new card cancels a close that was waiting: no open-shut-open flicker
        pendingClose = ""
        // A lone ring never morphs from or into another card (it would slide sideways as the box shrinks or grows):
        // the other card goes at once and the ring is born in its own place.
        const wantLone = newMode === "notice" && notice.wordless
        if (win.visible && wantLone !== lone) {
            host.hideWindow()
            island.slide = 1
        }
        const fresh = !win.visible
        if (fresh) {
            lone = wantLone
            island.morph = false
            mode = newMode
            island.slide = 1
            syncInput()
            mappedAt = Date.now()
            host.showWindow()
        } else {
            island.morph = true
            mode = newMode
        }
        shown = true
        hideTimer.interval = (newMode === "media" ? host.mediaSeconds : newMode === "notice" ? host.notice.seconds : host.bluetoothSeconds) * 1000
        armTimer()
        if (fresh) {
            probing = true                                 // the window is up but the card is still invisible: look where the pointer is
            probeTimer.restart()
        } else if (!probing) {
            holdUntil = Date.now() + host.minShowMs
            if (island.slide !== 0) enterAnim.restart()
        }
    }

    // The card appears only if the pointer is not where it would appear (it would cover what the person is pointing at).
    // A window that is mapped under a pointer gets its "enter" at once, even while the card is still invisible.
    function reveal() {
        probing = false
        // "hovered" alone can be stale: while the window is hidden Qt never hears the pointer leave. The pointer is
        // really there only if it reported itself after the window was mapped.
        const at = probe.point.scenePosition
        const r = restRect()
        if (probe.hovered && probeSeen >= mappedAt && at.x >= r.x && at.x <= r.x + r.width && at.y >= r.y && at.y <= r.y + r.height) {
            shown = false
            hideTimer.stop()
            idleTimer.stop()
            holdTimer.stop()
            pendingClose = ""
            actions.open = false
            host.hideWindow()
            island.slide = 1
            return
        }
        holdUntil = Date.now() + host.minShowMs
        if (pendingClose !== "") { holdTimer.interval = host.minShowMs; holdTimer.restart() }
        enterAnim.restart()
    }

    // Every "the time is up" or "the chorus is over" comes through here. A card that has been up for less than the
    // minimum stays until then; whatever asked is carried out afterwards (unless a newer card made it moot).
    function requestClose(reason) {
        if (!win.visible || !shown) return
        const wait = holdUntil - Date.now()
        if (probing || wait > 0) {
            pendingClose = reason
            if (!probing) { holdTimer.interval = wait; holdTimer.restart() }
            return
        }
        dismiss()
    }

    // Double-click: away in a blink.
    function dismissFast() {
        if (!win.visible) return
        if (liveKey !== "") { host.liveDismissed(liveKey); liveKey = "" }
        shown = false
        hideTimer.stop()
        idleTimer.stop()
        holdTimer.stop()
        pendingClose = ""
        probeTimer.stop()
        probing = false
        enterAnim.stop()
        exitAnim.stop()
        actions.open = false
        fastExit.restart()
    }

    function dismiss() {
        if (!win.visible) return
        shown = false
        actions.open = false
        hideTimer.stop()
        idleTimer.stop()
        holdTimer.stop()
        pendingClose = ""
        enterAnim.stop()
        exitAnim.restart()
    }

    // The card's resting rectangle (scaled around the corner it grows from), in window coordinates.
    function restRect() {
        const s = host.style.scale
        const ox = island.bare ? island.width / 2 : host.alignH === "left" ? 0 : host.alignH === "right" ? island.width : island.width / 2
        const oy = island.bare ? island.height / 2 : island.atTop ? 0 : island.height
        return Qt.rect(island.restX + ox * (1 - s), island.restY + oy * (1 - s), island.width * s, island.height * s)
    }

    // Input is limited to that rectangle.
    function syncInput() {
        const r = restRect()
        host.setInputRect(r.x, r.y, r.width, r.height)
    }

    Timer { id: hideTimer; onTriggered: win.requestClose("time") }
    Timer { id: probeTimer; interval: 120; onTriggered: win.reveal() }
    Timer {
        id: holdTimer
        onTriggered: {
            const reason = win.pendingClose
            win.pendingClose = ""
            if (!win.shown) return
            // The minimum is over. A "time is up" that came while the pointer arrived is held open again, as it always was.
            if (reason === "time" && (win.mode === "lyrics" || win.hovered || win.holdOpen)) win.armTimer()
            else win.dismiss()
        }
    }
    Timer { id: idleTimer; interval: host.idleMs; onTriggered: win.idle() }
    Connections { target: lyricsView; function onMoved() { win.touch() } }

    Connections {
        target: host
        function onMediaEvent(kind, direction) {
            media.apply(host.media, kind, direction, win.visible && win.shown)
            lyricsView.refresh(host.media)
            win.present("media")
        }
        function onMediaUpdated() { media.refresh(host.media, win.visible && win.shown); lyricsView.refresh(host.media) }
        function onLyricsStart() {
            lyricsView.apply(host.lyrics, host.media)
            win.present("lyrics")
        }
        function onLyricsEnd() { if (win.mode === "lyrics") win.requestClose("end") }
        function onMediaGone() { if (win.mode === "media") win.requestClose("end") }
        function onBluetoothEvent() {
            bt.apply(host.bt, win.visible && win.shown)
            win.present("bluetooth")
        }
        function onBtUpdated() { bt.refresh(host.bt) }
        function onLiveEvent() {
            // Another card is on screen: the live card waits (it comes back when that one is gone).
            if (win.visible && win.shown && !(win.mode === "notice" && win.liveKey !== "")) return
            notice.apply(host.liveNotice, win.visible && win.shown)
            win.liveKey = host.liveNotice.key
            win.present("notice")
        }
        function onLiveGone(key) {
            if (win.visible && win.mode === "notice" && win.liveKey === key) { win.liveKey = ""; win.dismiss() }
        }
        function onNoticeEvent() {
            win.liveKey = ""
            notice.apply(host.notice, win.visible && win.shown)
            win.present("notice")
        }
        function onLyricsChanged() { lyricsView.setLines(host.lyrics) }
    }

    Component.onCompleted: {
        media.load(host.media)
        syncInput()
    }

    // Sees the pointer even while the card is invisible (an item at opacity 0 receives no events).
    Item {
        anchors.fill: parent
        HoverHandler { id: probe; onPointChanged: win.probeSeen = Date.now() }
    }

    // -- the island --------------------------------------------------------
    Item {
        id: island
        objectName: "island"
        readonly property bool isMedia: win.mode === "media"
        readonly property bool isLyrics: win.mode === "lyrics"
        readonly property bool isBt: win.mode === "bluetooth"
        readonly property bool isNotice: win.mode === "notice"
        readonly property bool atTop: host.alignV === "top"
        property real slide: 1               // 1 = tucked off the edge, 0 = resting, <0 = overshoot
        property real kill: 0                // 0..1: the quick fade-out of a double-click
        property bool morph: false

        readonly property bool bare: isNotice && notice.wordless           // a lone ring: no box behind it
        width: isBt ? bt.preferredWidth : isNotice ? notice.preferredWidth : host.style.cardW
        height: isMedia ? host.style.mediaH : isLyrics ? host.style.lyricsH : bare ? notice.preferredHeight : 88
        property real radius: isBt || isNotice ? host.style.btRadius : host.style.mediaRadius
        readonly property bool calm: host.style.reducedMotion

        // One card turning into another: the box eases from one shape to the other (no overshoot), and the
        // two contents cross-dissolve over the same time, so something is always on screen and nothing ghosts.
        readonly property int morphMs: 540
        // Only a card that is on screen morphs. A hidden one takes its new shape at once, or the next card would be seen
        // arriving mid-way from the shape of the one before it (a lone ring sliding in from the side).
        readonly property bool morphing: win.visible && win.shown && !calm
        Behavior on width { enabled: island.morph && island.morphing; NumberAnimation { duration: island.morphMs; easing.type: Easing.InOutCubic } }
        Behavior on height { enabled: island.morph && island.morphing; NumberAnimation { duration: island.morphMs; easing.type: Easing.InOutCubic } }
        Behavior on radius { enabled: island.morph && island.morphing; NumberAnimation { duration: island.morphMs; easing.type: Easing.InOutCubic } }
        onWidthChanged: Qt.callLater(win.syncInput)
        onHeightChanged: Qt.callLater(win.syncInput)

        readonly property real restX: host.alignH === "left" ? host.insetX
                                    : host.alignH === "right" ? win.width - host.insetX - width
                                    : (win.width - width) / 2
        readonly property real restY: atTop ? host.insetY : win.height - host.insetY - height

        x: restX
        y: restY + (bare ? 0 : (atTop ? -1 : 1) * slide) * (height * host.style.scale + host.insetY + 40) * (calm ? 0.12 : 1)
        opacity: Math.max(0, Math.min(1, (1 - slide) * (calm ? 1.5 : 2.4))) * (1 - kill)
        scale: host.style.scale * (bare || calm ? (bare ? 1 : 0.985 + 0.015 * (1 - slide)) : 0.9 + 0.1 * (1 - slide)) * (1 - 0.03 * kill)    // a lone ring only fades: no movement, no pop
        transformOrigin: bare ? Item.Center            // a lone ring grows and shrinks around itself, not from a corner
                       : atTop ? (host.alignH === "left" ? Item.TopLeft : host.alignH === "right" ? Item.TopRight : Item.Top)
                               : (host.alignH === "left" ? Item.BottomLeft : host.alignH === "right" ? Item.BottomRight : Item.Bottom)

        // Bare-card gestures. This sits under everything else, so buttons and the seek bar keep their clicks.
        Item {
            anchors.fill: parent
            TapHandler { acceptedButtons: Qt.LeftButton; onDoubleTapped: win.dismissFast() }
            TapHandler { acceptedButtons: Qt.RightButton; onTapped: actions.open = !actions.open }
        }

        // drop shadow
        Rectangle {
            id: caster
            anchors.fill: parent
            radius: island.radius
            color: "black"
            visible: false
        }
        MultiEffect {
            source: caster
            anchors.fill: caster
            visible: host.style.shadow && !island.bare
            shadowEnabled: true
            shadowColor: "black"
            shadowOpacity: 0.55
            shadowBlur: 1.0
            shadowVerticalOffset: 14
        }

        // rounded content
        Item {
            id: content
            anchors.fill: parent
            layer.enabled: true
            layer.effect: MultiEffect {
                maskEnabled: true
                maskSource: maskItem
                maskThresholdMin: 0.5
                maskSpreadAtMin: 1.0
            }

            Rectangle { anchors.fill: parent; color: "#0c0c0f"; opacity: island.bare ? 0 : 1; Behavior on opacity { NumberAnimation { duration: 200 } } }

            MediaView {
                id: media
                objectName: "viewMedia"
                hovered: win.hovered && !win.holdOpen          // the action bar covers the card: no buttons behind it
                active: win.visible
                opacity: island.isMedia ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: island.calm ? 120 : island.morphMs * 0.6; easing.type: Easing.InOutQuad } }
            }
            LyricsView {
                id: lyricsView
                objectName: "viewLyrics"
                active: win.visible && island.isLyrics
                hovered: win.hovered && !win.holdOpen          // the action bar covers the card: no buttons behind it
                opacity: island.isLyrics ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: island.calm ? 120 : island.morphMs * 0.6; easing.type: Easing.InOutQuad } }
            }
            BluetoothView {
                id: bt
                objectName: "viewBt"
                active: win.visible
                width: parent.width
                height: parent.height
                opacity: island.isBt ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: island.calm ? 120 : island.morphMs * 0.6; easing.type: Easing.InOutQuad } }
            }
            NoticeView {
                id: notice
                objectName: "viewNotice"
                active: win.visible
                width: parent.width
                height: parent.height
                opacity: island.isNotice ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: island.calm ? 120 : island.morphMs * 0.6; easing.type: Easing.InOutQuad } }
            }

            // inside the rounded layer, so its corners follow the card's
            ActionBar {
                id: actions
                anchors.fill: parent
                mode: win.mode
            }
        }
        Item {
            id: maskItem
            anchors.fill: parent
            visible: false
            layer.enabled: true
            Rectangle { anchors.fill: parent; radius: island.radius; color: "black" }
        }

        // glass edge
        Rectangle {
            anchors.fill: parent
            radius: island.radius
            color: "transparent"
            visible: !island.bare
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.14)
        }

        HoverHandler {
            id: hover
            property point last: Qt.point(-1, -1)
            // The pointer moving over the card. (Qt also re-sends the position when things animate under a pointer that
            // is not moving; only a different position on the screen counts.)
            onPointChanged: {
                const p = point.scenePosition
                if (p.x !== last.x || p.y !== last.y) { last = p; win.touch() }
            }
        }
        PointHandler { onPointChanged: win.touch() }              // ...or pressing on it (the seek bar, a button)
    }

    NumberAnimation {
        id: enterAnim
        target: island
        property: "slide"
        to: 0
        duration: island.calm ? 240 : 760
        easing.type: island.calm ? Easing.OutCubic : Easing.OutBack
        easing.overshoot: 0.8
        onFinished: island.morph = true
    }
    SequentialAnimation {
        id: fastExit
        NumberAnimation { target: island; property: "kill"; to: 1; duration: 150; easing.type: Easing.OutQuad }
        ScriptAction { script: { host.hideWindow(); island.slide = 1; island.kill = 0 } }
    }
    SequentialAnimation {
        id: exitAnim
        NumberAnimation { target: island; property: "slide"; to: 1; duration: island.calm ? 200 : 380; easing.type: Easing.InCubic }
        ScriptAction { script: host.hideWindow() }
    }
}
