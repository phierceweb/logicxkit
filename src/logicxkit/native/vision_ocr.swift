// auocr — OCR an image via Apple Vision; JSON lines of {text, conf, x, y, w, h}.
// usage: swift auocr.swift <image path>
// Bounding boxes are normalized [0,1], origin bottom-left (Vision convention).
import AppKit
import Foundation
import Vision

func die(_ msg: String) -> Never {
    FileHandle.standardError.write(("ERROR: " + msg + "\n").data(using: .utf8)!)
    exit(1)
}

guard CommandLine.arguments.count == 2 else { die("usage: auocr <image>") }
let path = CommandLine.arguments[1]
guard let img = NSImage(contentsOfFile: path),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil)
else { die("cannot load image \(path)") }

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false  // keep "-7.5", "4k37", "B 15" verbatim

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do { try handler.perform([request]) } catch { die("vision failed: \(error)") }

var rows: [[String: Any]] = []
for obs in request.results ?? [] {
    guard let cand = obs.topCandidates(1).first else { continue }
    let bb = obs.boundingBox
    rows.append(["text": cand.string, "conf": Double(cand.confidence),
                 "x": bb.origin.x, "y": bb.origin.y,
                 "w": bb.size.width, "h": bb.size.height])
}
let out: [String: Any] = ["image": path, "width": cg.width, "height": cg.height,
                          "count": rows.count, "items": rows]
print(String(data: try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]),
             encoding: .utf8)!)
