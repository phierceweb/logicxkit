// auprobe — headless Audio Unit parameter introspection.
// usage:
//   swift auprobe.swift list <type4cc> <subtype4cc> <manu4cc>   e.g. list aufx FC2p FabF
//   swift auprobe.swift preset <file.aupreset>                  instantiate + load + dump values
import AudioToolbox
import Foundation

func fourCC(_ s: String) -> OSType {
    var v: OSType = 0
    for b in s.utf8 { v = (v << 8) | OSType(b) }
    return v
}
func ccString(_ v: UInt32) -> String {
    let bytes = [UInt8((v >> 24) & 0xFF), UInt8((v >> 16) & 0xFF), UInt8((v >> 8) & 0xFF), UInt8(v & 0xFF)]
    return String(bytes: bytes, encoding: .ascii) ?? String(v)
}
func die(_ msg: String) -> Never {
    FileHandle.standardError.write(("ERROR: " + msg + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 2 else { die("usage: list <t> <st> <m> | preset <file>") }
let mode = args[1]

var desc = AudioComponentDescription(componentType: 0, componentSubType: 0,
                                     componentManufacturer: 0, componentFlags: 0, componentFlagsMask: 0)
var presetPlist: [String: Any]? = nil

if mode == "list" {
    guard args.count == 5 else { die("list needs 3 four-CCs") }
    desc.componentType = fourCC(args[2])
    desc.componentSubType = fourCC(args[3])
    desc.componentManufacturer = fourCC(args[4])
} else if mode == "preset" {
    guard args.count == 3 else { die("preset needs a file path") }
    guard let data = FileManager.default.contents(atPath: args[2]) else { die("cannot read \(args[2])") }
    guard let pl = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
    else { die("not a plist") }
    presetPlist = pl
    desc.componentType = OSType((pl["type"] as? NSNumber)?.uint32Value ?? 0)
    desc.componentSubType = OSType((pl["subtype"] as? NSNumber)?.uint32Value ?? 0)
    desc.componentManufacturer = OSType((pl["manufacturer"] as? NSNumber)?.uint32Value ?? 0)
} else {
    die("unknown mode \(mode)")
}

guard let comp = AudioComponentFindNext(nil, &desc) else {
    die("component not found: \(ccString(desc.componentType))/\(ccString(desc.componentSubType))/\(ccString(desc.componentManufacturer))")
}
var cname: Unmanaged<CFString>?
AudioComponentCopyName(comp, &cname)
let componentName = cname?.takeRetainedValue() as String? ?? "?"

var unitOpt: AudioUnit?
var st = AudioComponentInstanceNew(comp, &unitOpt)
guard st == noErr, let unit = unitOpt else { die("instantiate failed: \(st)") }
st = AudioUnitInitialize(unit)
if st != noErr { FileHandle.standardError.write("WARN: init returned \(st)\n".data(using: .utf8)!) }

if let pl = presetPlist {
    var cf = pl as CFPropertyList
    let err = withUnsafeMutablePointer(to: &cf) { ptr -> OSStatus in
        AudioUnitSetProperty(unit, kAudioUnitProperty_ClassInfo, kAudioUnitScope_Global, 0,
                             ptr, UInt32(MemoryLayout<CFPropertyList>.size))
    }
    if err != noErr { die("ClassInfo restore failed: \(err)") }
}

var psize: UInt32 = 0
AudioUnitGetPropertyInfo(unit, kAudioUnitProperty_ParameterList, kAudioUnitScope_Global, 0, &psize, nil)
let n = Int(psize) / MemoryLayout<AudioUnitParameterID>.size
var ids = [AudioUnitParameterID](repeating: 0, count: max(n, 1))
if n > 0 {
    AudioUnitGetProperty(unit, kAudioUnitProperty_ParameterList, kAudioUnitScope_Global, 0, &ids, &psize)
}

func unitName(_ u: AudioUnitParameterUnit) -> String {
    switch u {
    case .generic: return "generic"; case .indexed: return "indexed"; case .boolean: return "bool"
    case .percent: return "%"; case .seconds: return "s"; case .sampleFrames: return "frames"
    case .phase: return "phase"; case .rate: return "rate"; case .hertz: return "Hz"
    case .cents: return "cents"; case .relativeSemiTones: return "semitones"
    case .midiNoteNumber: return "midiNote"; case .midiController: return "midiCC"
    case .decibels: return "dB"; case .linearGain: return "linGain"; case .degrees: return "deg"
    case .equalPowerCrossfade: return "xfade"; case .mixerFaderCurve1: return "faderCurve"
    case .pan: return "pan"; case .meters: return "m"; case .absoluteCents: return "absCents"
    case .octaves: return "oct"; case .BPM: return "bpm"; case .beats: return "beats"
    case .milliseconds: return "ms"; case .ratio: return "ratio"; case .customUnit: return "custom"
    default: return "unit\(u.rawValue)"
    }
}

var out: [[String: Any]] = []
for pid in ids.prefix(n) {
    var info = AudioUnitParameterInfo()
    var isize = UInt32(MemoryLayout<AudioUnitParameterInfo>.size)
    let e = AudioUnitGetProperty(unit, kAudioUnitProperty_ParameterInfo, kAudioUnitScope_Global, pid, &info, &isize)
    var name = "param\(pid)"
    if e == noErr {
        if info.flags.contains(.flag_HasCFNameString), let cf = info.cfNameString {
            name = cf.takeUnretainedValue() as String
        } else {
            name = withUnsafeBytes(of: info.name) { raw in
                String(cString: raw.bindMemory(to: CChar.self).baseAddress!)
            }
        }
    }
    var row: [String: Any] = [
        "id": Int(pid), "name": name,
        "unit": e == noErr ? unitName(info.unit) : "?",
        "min": e == noErr ? Double(info.minValue) : 0,
        "max": e == noErr ? Double(info.maxValue) : 0,
        "default": e == noErr ? Double(info.defaultValue) : 0,
    ]
    if presetPlist != nil {
        var val: AudioUnitParameterValue = 0
        if AudioUnitGetParameter(unit, pid, kAudioUnitScope_Global, 0, &val) == noErr {
            row["value"] = Double(val)
        }
        // valueString: ask the AU to format the value the way its UI would
        withUnsafeMutablePointer(to: &val) { vptr in
            var strInfo = AudioUnitParameterStringFromValue(inParamID: pid, inValue: vptr, outString: nil)
            var ssize = UInt32(MemoryLayout<AudioUnitParameterStringFromValue>.size)
            if AudioUnitGetProperty(unit, kAudioUnitProperty_ParameterStringFromValue,
                                    kAudioUnitScope_Global, 0, &strInfo, &ssize) == noErr,
               let s = strInfo.outString {
                row["display"] = s.takeUnretainedValue() as String
            }
        }
    }
    out.append(row)
}

let result: [String: Any] = [
    "component": componentName,
    "type": ccString(desc.componentType), "subtype": ccString(desc.componentSubType),
    "manufacturer": ccString(desc.componentManufacturer),
    "paramCount": n, "params": out,
]
let json = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
print(String(data: json, encoding: .utf8)!)
