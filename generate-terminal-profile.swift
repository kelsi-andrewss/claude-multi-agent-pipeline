import Foundation
import AppKit

func colorData(_ hex: String) -> Data {
    let h = hex.dropFirst() // remove #
    let scanner = Scanner(string: String(h))
    var rgb: UInt64 = 0
    scanner.scanHexInt64(&rgb)
    let r = CGFloat((rgb >> 16) & 0xFF) / 255.0
    let g = CGFloat((rgb >> 8) & 0xFF) / 255.0
    let b = CGFloat(rgb & 0xFF) / 255.0
    let color = NSColor(calibratedRed: r, green: g, blue: b, alpha: 1.0)
    return try! NSKeyedArchiver.archivedData(withRootObject: color, requiringSecureCoding: false)
}

// Neutral dark theme that stays out of Claude Code's way.
// The banner uses 256-color codes directly — those render fine on any dark bg.
// ANSI slots stay muted so they don't clash with Claude Code's hardcoded UI colors
// (status bar, safety prompts, permission dialogs, etc).
let profile: [String: Any] = [
    "name": "Claude Pastel",
    "type": "Window Settings",

    // Core — M3 dark surface (tone 6) + on-surface (tone 90)
    "BackgroundColor":            colorData("#141414"),
    "TextColor":                  colorData("#e6e6e6"),
    "TextBoldColor":              colorData("#f0f0f0"),
    "CursorColor":                colorData("#e6e6e6"),
    "CursorTextColor":            colorData("#141414"),
    "SelectionColor":             colorData("#2b2b2b"),
    "BackgroundBlur":             0.0,
    "BackgroundAlphaInactive":    1.0,
    "BackgroundSettingsForInactiveWindows": false,

    // ANSI Normal — muted, functional
    "ANSIBlackColor":             colorData("#2a2a2a"),  // slightly above bg for dim text
    "ANSIRedColor":               colorData("#d08080"),  // dusty rose — 5.2:1
    "ANSIGreenColor":             colorData("#7aab7a"),  // muted sage
    "ANSIYellowColor":            colorData("#c4a84e"),  // warm amber
    "ANSIBlueColor":              colorData("#7799bb"),  // steel blue — 5.2:1
    "ANSIMagentaColor":           colorData("#aa85b5"),  // muted lilac — 5.0:1
    "ANSICyanColor":              colorData("#6aabab"),  // muted teal
    "ANSIWhiteColor":             colorData("#e6e6e6"),  // matches text

    // ANSI Bright — lifted for emphasis, still restrained
    "ANSIBrightBlackColor":       colorData("#5a5a5a"),  // comments, dim text
    "ANSIBrightRedColor":         colorData("#d09090"),  // soft coral
    "ANSIBrightGreenColor":       colorData("#98c498"),  // light sage
    "ANSIBrightYellowColor":      colorData("#d4c088"),  // warm cream
    "ANSIBrightBlueColor":        colorData("#88a8c8"),  // light steel
    "ANSIBrightMagentaColor":     colorData("#b898c0"),  // light lavender
    "ANSIBrightCyanColor":        colorData("#88c8c8"),  // light teal
    "ANSIBrightWhiteColor":       colorData("#f0f0f0"),  // matches bold text

    // Font — Menlo 13pt (macOS default monospace)
    "Font": try! NSKeyedArchiver.archivedData(
        withRootObject: NSFont(name: "MenloRegular", size: 13.0) ?? NSFont.monospacedSystemFont(ofSize: 13.0, weight: .regular),
        requiringSecureCoding: false
    ),

    // Window
    "columnCount":                120,
    "rowCount":                   36,
    "ShouldLimitScrollback":      0,
    "ScrollbackLines":            10000,
    "UseBoldFonts":               true,
    "UseBrightBold":              true,
    "ShowRepresentedURLInTitle":   false,
    "ShowActiveProcessInTitle":    true,
    "ShowWindowSettingsNameInTitle": false,
    "ShowCommandKeyInTitle":       false,
    "ShowDimensionsInTitle":       false,
]

let data = try! PropertyListSerialization.data(fromPropertyList: profile, format: .xml, options: 0)
let outputPath = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "Claude-Pastel.terminal"
try! data.write(to: URL(fileURLWithPath: outputPath))
print("Created \(outputPath)")
