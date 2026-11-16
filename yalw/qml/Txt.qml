import QtQuick

Text {
    color: "white"
    font.family: host.fontFamily
    font.hintingPreference: Font.PreferNoHinting
    renderType: Text.QtRendering
    elide: Text.ElideRight
    maximumLineCount: 1
}
