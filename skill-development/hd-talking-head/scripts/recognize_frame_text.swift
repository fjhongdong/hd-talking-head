#!/usr/bin/env swift
import Foundation
import Vision
import ImageIO
import CoreGraphics

struct Observation: Codable {
    let text: String
    let confidence: Float
    let bbox: [Double]
    let alternatives: [String]
}
struct ImageResult: Codable {
    let path: String
    let width: Int
    let height: Int
    let status: String
    let observations: [Observation]
    let error: String?
}
struct Output: Codable {
    let schema_version: Int
    let engine: String
    let images: [ImageResult]
}

func fail(_ message: String) -> Never {
    let output = Output(schema_version: 1, engine: "apple-vision", images: [])
    if let data = try? JSONEncoder().encode(output), let text = String(data: data, encoding: .utf8) {
        FileHandle.standardOutput.write(Data((text + "\n").utf8))
    }
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(2)
}

let paths = Array(CommandLine.arguments.dropFirst())
if paths.isEmpty { fail("usage: recognize_frame_text.swift IMAGE [IMAGE ...]") }

var results: [ImageResult] = []
var hadImageError = false
for path in paths {
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        hadImageError = true
        results.append(ImageResult(path: path, width: 0, height: 0, status: "error", observations: [], error: "cannot decode image"))
        continue
    }
    let width = image.width
    let height = image.height
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    request.minimumTextHeight = 0.005
    do {
        let handler = VNImageRequestHandler(cgImage: image, options: [:])
        try handler.perform([request])
        let observations = (request.results ?? []).compactMap { result -> Observation? in
            guard let candidate = result.topCandidates(1).first else { return nil }
            let box = result.boundingBox
            let x = Double(box.minX) * Double(width)
            let y = (1.0 - Double(box.maxY)) * Double(height)
            let w = Double(box.width) * Double(width)
            let h = Double(box.height) * Double(height)
            let alternatives = result.topCandidates(5).dropFirst().map { $0.string }
            return Observation(text: candidate.string, confidence: candidate.confidence,
                               bbox: [x, y, w, h], alternatives: alternatives)
        }
        results.append(ImageResult(path: path, width: width, height: height, status: "ok", observations: observations, error: nil))
    } catch {
        hadImageError = true
        results.append(ImageResult(path: path, width: width, height: height, status: "error", observations: [], error: String(describing: error)))
    }
}

let output = Output(schema_version: 1, engine: "apple-vision", images: results)
do {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    let data = try encoder.encode(output)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    fail("cannot encode output: \(error)")
}

if hadImageError { exit(1) }
