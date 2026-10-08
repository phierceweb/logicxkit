// axact get|press|set|actions|attrs <path like w0.6.0.1.24> [value] : act on one element of Logic Pro's AX tree
import AppKit
import ApplicationServices

let args = CommandLine.arguments
guard args.count >= 3 else { print("usage: axact get|press|set|actions|attrs|children <path> [value]"); exit(2) }
let mode = args[1], path = args[2]
guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.logic10").first else { print("NO LOGIC"); exit(1) }
let axApp = AXUIElementCreateApplication(app.processIdentifier)
func attr(_ e: AXUIElement, _ name: String) -> AnyObject? {
    var v: AnyObject?; return AXUIElementCopyAttributeValue(e, name as CFString, &v) == .success ? v : nil
}
func str(_ e: AXUIElement, _ name: String) -> String {
    guard let v = attr(e, name) else { return "" }
    if let s = v as? String { return s }
    if let n = v as? NSNumber { return n.stringValue }
    if CFGetTypeID(v) == AXValueGetTypeID() {
        let av = v as! AXValue; var p = CGPoint.zero; var sz = CGSize.zero
        if AXValueGetType(av) == .cgPoint, AXValueGetValue(av, .cgPoint, &p) { return "\(Int(p.x)),\(Int(p.y))" }
        if AXValueGetType(av) == .cgSize, AXValueGetValue(av, .cgSize, &sz) { return "\(Int(sz.width))x\(Int(sz.height))" }
    }
    return String(describing: v).prefix(80).description
}
func children(_ e: AXUIElement) -> [AXUIElement] { (attr(e, kAXChildrenAttribute) as? [AXUIElement]) ?? [] }
var parts = path.split(separator: ".").map(String.init)
guard parts.first?.hasPrefix("w") == true, let wi = Int(parts.removeFirst().dropFirst()) else { print("BAD PATH"); exit(2) }
// help tags (tooltips) are windows too and come first; only real windows count
let windows = ((attr(axApp, kAXWindowsAttribute) as? [AXUIElement]) ?? []).filter { str($0, kAXRoleAttribute) == "AXWindow" }
guard wi < windows.count else { print("NO WINDOW \(wi)"); exit(1) }
var e = windows[wi]
for p in parts {
    let cs = children(e)
    guard let i = Int(p), i < cs.count else { print("NO CHILD \(p) (\(cs.count) children)"); exit(1) }
    e = cs[i]
}
func describe(_ e: AXUIElement) -> String {
    "\(str(e, kAXRoleAttribute)) | d=\(str(e, kAXDescriptionAttribute)) | t=\(str(e, kAXTitleAttribute)) | v=\(str(e, kAXValueAttribute)) | @\(str(e, kAXPositionAttribute)) \(str(e, kAXSizeAttribute))"
}
switch mode {
case "get": print(describe(e))
case "press":
    let before = describe(e)
    let r = AXUIElementPerformAction(e, kAXPressAction as CFString)
    usleep(500000)
    print("press \(r == .success ? "ok" : "err \(r.rawValue)")\n  \(before)\n  \(describe(e))")
case "set":
    guard args.count > 3 else { print("need value"); exit(2) }
    let before = describe(e)
    let v = args[3]
    var r: AXError
    if let n = Double(v) { r = AXUIElementSetAttributeValue(e, kAXValueAttribute as CFString, NSNumber(value: n)) }
    else { r = AXUIElementSetAttributeValue(e, kAXValueAttribute as CFString, v as CFString) }
    usleep(500000)
    print("set \(r == .success ? "ok" : "err \(r.rawValue)")\n  \(before)\n  \(describe(e))")
case "pick":
    // press a popup, then press the menu item titled <value> ("~part" matches a substring; submenus searched)
    guard args.count > 3 else { print("need item"); exit(2) }
    let want = args[3]
    var menuEl: AXUIElement? = nil
    for action in [kAXPressAction, kAXShowMenuAction] {     // header popups only open on ShowMenu
        AXUIElementPerformAction(e, action as CFString)
        for _ in 0..<8 {
            usleep(300000)
            if let m = children(e).first(where: { str($0, kAXRoleAttribute) == "AXMenu" }) { menuEl = m; break }
        }
        if menuEl != nil { break }
    }
    guard let menu = menuEl else { print("NO MENU"); exit(1) }
    func find(_ m: AXUIElement) -> AXUIElement? {
        for item in children(m) {
            let t = str(item, kAXTitleAttribute)
            if t == want || (want.hasPrefix("~") && t.contains(want.dropFirst())) { return item }
            for sub in children(item) where str(sub, kAXRoleAttribute) == "AXMenu" { if let f = find(sub) { return f } }
        }
        return nil
    }
    if let item = find(menu) {
        let r = AXUIElementPerformAction(item, kAXPressAction as CFString)
        usleep(1500000)
        print("pick \(r == .success ? "ok" : "err \(r.rawValue)") -> \(describe(e))")
    } else {
        let titles = children(menu).map { str($0, kAXTitleAttribute) }
        AXUIElementPerformAction(menu, kAXCancelAction as CFString)
        print("NO ITEM \(want); menu: \(titles)")
        exit(1)
    }
case "do":
    // perform any named action (AXScrollToVisible, AXShowMenu, AXCancel ...)
    guard args.count > 3 else { print("need action"); exit(2) }
    let r = AXUIElementPerformAction(e, args[3] as CFString)
    usleep(500000)
    print("do \(args[3]) \(r == .success ? "ok" : "err \(r.rawValue)") -> \(describe(e))")
case "actions":
    var names: CFArray?
    AXUIElementCopyActionNames(e, &names)
    print(describe(e)); print((names as? [String]) ?? [])
case "attrs":
    var names: CFArray?
    AXUIElementCopyAttributeNames(e, &names)
    print(describe(e))
    for n in (names as? [String]) ?? [] { print("  \(n) = \(str(e, n))") }
case "children":
    for (i, c) in children(e).enumerated() { print("\(path).\(i) \(describe(c))") }
default: print("unknown mode")
}
