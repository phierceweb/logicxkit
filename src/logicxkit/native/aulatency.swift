// aulatency — report an Audio Unit's reported processing latency.
//
//   swift aulatency.swift <type4cc> <subtype4cc> <manu4cc> [sampleRate]
//
// Reads kAudioUnitProperty_LatencySamples, which is what a host uses for delay compensation
// and therefore what a player actually feels while monitoring. Latency is queried AFTER
// initialisation at the given sample rate, because some plugins report 0 until initialised.
import AudioToolbox
import Foundation

func fourCC(_ s: String) -> OSType {
    var v: OSType = 0
    for b in s.utf8 { v = (v << 8) | OSType(b) }
    return v
}
func die(_ m: String) -> Never {
    FileHandle.standardError.write(("ERROR: " + m + "\n").data(using: .utf8)!)
    exit(1)
}

let a = CommandLine.arguments
guard a.count >= 4 else { die("usage: <type> <subtype> <manu> [sampleRate]") }
let sampleRate = a.count > 4 ? Double(a[4]) ?? 44100 : 44100

var desc = AudioComponentDescription(componentType: fourCC(a[1]), componentSubType: fourCC(a[2]),
                                     componentManufacturer: fourCC(a[3]),
                                     componentFlags: 0, componentFlagsMask: 0)
guard let comp = AudioComponentFindNext(nil, &desc) else { die("component not found") }
var nameRef: Unmanaged<CFString>?
AudioComponentCopyName(comp, &nameRef)
let name = nameRef?.takeRetainedValue() as String? ?? "?"

var unitOpt: AudioUnit?
guard AudioComponentInstanceNew(comp, &unitOpt) == noErr, let unit = unitOpt
else { die("instantiate failed") }

var sr = sampleRate
AudioUnitSetProperty(unit, kAudioUnitProperty_SampleRate, kAudioUnitScope_Input, 0,
                     &sr, UInt32(MemoryLayout<Double>.size))
AudioUnitSetProperty(unit, kAudioUnitProperty_SampleRate, kAudioUnitScope_Output, 0,
                     &sr, UInt32(MemoryLayout<Double>.size))
if AudioUnitInitialize(unit) != noErr {
    FileHandle.standardError.write("WARN: initialize failed\n".data(using: .utf8)!)
}

var latency: Double = 0
var size = UInt32(MemoryLayout<Double>.size)
let err = AudioUnitGetProperty(unit, kAudioUnitProperty_Latency, kAudioUnitScope_Global, 0,
                               &latency, &size)
var tail: Double = 0
size = UInt32(MemoryLayout<Double>.size)
AudioUnitGetProperty(unit, kAudioUnitProperty_TailTime, kAudioUnitScope_Global, 0, &tail, &size)

let samples = latency * sr
print("""
{"name": "\(name)", "ok": \(err == noErr), "sampleRate": \(sr), \
"latencySeconds": \(latency), "latencySamples": \(Int(samples.rounded())), \
"latencyMs": \(latency * 1000), "tailSeconds": \(tail)}
""")
AudioUnitUninitialize(unit)
AudioComponentInstanceDispose(unit)
