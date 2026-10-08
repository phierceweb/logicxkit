// axdump [maxDepth] [window-index] [filter] : walk Logic Pro's AX tree, one line per element with its index path
import AppKit
import ApplicationServices

let args = CommandLine.arguments
let maxDepth = args.count > 1 ? Int(args[1]) ?? 6 : 6
let winIndex = args.count > 2 ? Int(args[2]) ?? 0 : 0
let filter = args.count > 3 ? args[3] : ""

guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.logic10").first else {
    print("NO LOGIC"); exit(1)
}
let axApp = AXUIElementCreateApplication(app.processIdentifier)

func attr(_ e: AXUIElement, _ name: String) -> AnyObject? {
    var v: AnyObject?
    let r = AXUIElementCopyAttributeValue(e, name as CFString, &v)
    return r == .success ? v : nil
}
func str(_ e: AXUIElement, _ name: String) -> String {
    guard let v = attr(e, name) else { return "" }
    if let s = v as? String { return s }
    if let n = v as? NSNumber { return n.stringValue }
    if CFGetTypeID(v) == AXValueGetTypeID() {
        let av = v as! AXValue
        var p = CGPoint.zero; var sz = CGSize.zero
        if AXValueGetType(av) == .cgPoint, AXValueGetValue(av, .cgPoint, &p) { return "\(Int(p.x)),\(Int(p.y))" }
        if AXValueGetType(av) == .cgSize, AXValueGetValue(av, .cgSize, &sz) { return "\(Int(sz.width))x\(Int(sz.height))" }
    }
    return String(describing: v).prefix(60).description
}
func children(_ e: AXUIElement) -> [AXUIElement] {
    return (attr(e, kAXChildrenAttribute) as? [AXUIElement]) ?? []
}
var lines: [String] = []
func walk(_ e: AXUIElement, _ path: String, _ depth: Int) {
    let role = str(e, kAXRoleAttribute)
    let sub = str(e, kAXSubroleAttribute)
    let desc = str(e, kAXDescriptionAttribute)
    let title = str(e, kAXTitleAttribute)
    let value = str(e, kAXValueAttribute)
    let pos = str(e, kAXPositionAttribute)
    let size = str(e, kAXSizeAttribute)
    let en = str(e, kAXEnabledAttribute)
    let line = "\(String(repeating: "  ", count: depth))\(path) \(role)\(sub.isEmpty ? "" : "/" + sub) | d=\(desc) | t=\(title) | v=\(value) | @\(pos) \(size)\(en == "0" ? " DISABLED" : "")"
    if filter.isEmpty || line.lowercased().contains(filter.lowercased()) { lines.append(line) }
    if depth >= maxDepth { return }
    for (i, c) in children(e).enumerated() { walk(c, "\(path).\(i)", depth + 1) }
}
// help tags (tooltips) are windows too and come first; only real windows count
let windows = ((attr(axApp, kAXWindowsAttribute) as? [AXUIElement]) ?? []).filter { str($0, kAXRoleAttribute) == "AXWindow" }
if windows.count <= winIndex { print("NO WINDOW \(winIndex) of \(windows.count)"); exit(1) }
walk(windows[winIndex], "w\(winIndex)", 0)
print(lines.joined(separator: "\n"))
