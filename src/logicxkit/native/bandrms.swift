// bandrms — the RMS level of an audio file per hop, all channels pooled, optionally band-limited.
//
//   swift bandrms.swift <file> <hop_ms> [<low_hz> <high_hz>]
//
// Prints "rate hop frames count" then one RMS per line in 0..1. The band is a fourth-order
// Butterworth high-pass at low_hz and low-pass at high_hz (two biquads each, Q 0.5412 and
// 1.3066). The tail shorter than a hop is folded into the last hop, as the peak envelope does.
import AVFoundation
import Accelerate

func die(_ m: String) -> Never {
    FileHandle.standardError.write(("ERROR: " + m + "\n").data(using: .utf8)!)
    exit(1)
}

let a = CommandLine.arguments
guard a.count == 3 || a.count == 5 else { die("usage: <file> <hop_ms> [<low_hz> <high_hz>]") }
guard let hopMs = Int(a[2]), hopMs > 0 else { die("hop_ms must be a positive integer") }
let file: AVAudioFile
do {
    file = try AVAudioFile(forReading: URL(fileURLWithPath: a[1]), commonFormat: .pcmFormatFloat32, interleaved: false)
} catch {
    die("cannot read \(a[1]): \(error)")
}
let rate = file.processingFormat.sampleRate
let channels = Int(file.processingFormat.channelCount)
let frames = Int(file.length)
let hop = max(1, Int(rate) * hopMs / 1000)
let hops = max(0, frames / hop)
if hops == 0 {
    FileHandle.standardOutput.write("\(Int(rate)) \(hop) \(frames) 0\n".data(using: .utf8)!)
    exit(0)
}

// RBJ cookbook sections, a0 normalised out: [b0, b1, b2, a1, a2].
func section(_ hz: Double, q: Double, highPass: Bool) -> [Double] {
    let w = 2 * Double.pi * hz / rate
    let alpha = sin(w) / (2 * q), c = cos(w)
    let a0 = 1 + alpha
    let b0 = highPass ? (1 + c) / 2 : (1 - c) / 2
    let b1 = highPass ? -(1 + c) : (1 - c)
    return [b0 / a0, b1 / a0, b0 / a0, -2 * c / a0, (1 - alpha) / a0]
}
var filters: [vDSP.Biquad<Float>] = []
if a.count == 5 {
    guard let low = Double(a[3]), let high = Double(a[4]), low > 0, high > low, high < rate / 2 else {
        die("the band needs 0 < low_hz < high_hz < half the sample rate")
    }
    let coefficients = section(low, q: 0.5412, highPass: true) + section(low, q: 1.3066, highPass: true)
        + section(high, q: 0.5412, highPass: false) + section(high, q: 1.3066, highPass: false)
    for _ in 0..<channels {
        guard let biquad = vDSP.Biquad(coefficients: coefficients, channelCount: 1, sectionCount: 4, ofType: Float.self)
        else { die("biquad setup failed") }
        filters.append(biquad)
    }
}

var sums = [Double](repeating: 0, count: max(hops, 1))
var position = 0
guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: 1 << 16) else { die("buffer") }
while position < frames {
    do { try file.read(into: buffer) } catch { die("read failed at frame \(position): \(error)") }
    let n = Int(buffer.frameLength)
    if n == 0 { break }
    for c in 0..<channels {
        var x = Array(UnsafeBufferPointer(start: buffer.floatChannelData![c], count: n))
        if !filters.isEmpty { x = filters[c].apply(input: x) }
        var k = 0
        while k < n {
            let h = min(hops - 1, (position + k) / hop)       // the tail folds into the last hop
            let end = h == hops - 1 ? n : min(n, (h + 1) * hop - position)
            var s: Float = 0
            vDSP_svesq(Array(x[k..<end]), 1, &s, vDSP_Length(end - k))
            sums[h] += Double(s)
            k = end
        }
    }
    position += n
}
var out = "\(Int(rate)) \(hop) \(frames) \(hops)\n"
for h in 0..<hops {
    let count = Double((h == hops - 1 ? frames - h * hop : hop) * channels)
    out += String(format: "%.7f\n", (sums[h] / max(count, 1)).squareRoot())
}
FileHandle.standardOutput.write(out.data(using: .utf8)!)
