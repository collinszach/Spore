import Foundation
import AVFoundation

/// Abstraction over audio recording so `VoiceCaptureViewModel` can be tested
/// without touching AVFoundation/hardware (Story 2.6).
protocol AudioRecording: AnyObject, Sendable {
    /// Whether a recording is currently in progress.
    var isRecording: Bool { get }

    /// Requests mic permission (if needed) and starts recording to a temp
    /// `.m4a` (AAC) file. Throws if permission is denied or the recorder
    /// fails to start.
    func start() async throws

    /// Stops the current recording and returns the file URL of the
    /// recorded audio, or `nil` if nothing was recorded.
    func stop() async -> URL?
}

/// Errors surfaced by `AVAudioRecorderRecording`.
enum AudioRecordingError: Error, Equatable {
    case permissionDenied
    case recorderFailed(String)
}

/// Production `AudioRecording` backed by `AVAudioRecorder`, recording to a
/// temp `.m4a` (AAC) file in the caches directory.
final class AVAudioRecorderRecording: NSObject, AudioRecording, @unchecked Sendable {
    private var recorder: AVAudioRecorder?
    private var currentURL: URL?

    private(set) var isRecording: Bool = false

    func start() async throws {
        let session = AVAudioSession.sharedInstance()

        let granted = await requestPermission(session: session)
        guard granted else {
            throw AudioRecordingError.permissionDenied
        }

        do {
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
            try session.setActive(true)
        } catch {
            throw AudioRecordingError.recorderFailed(error.localizedDescription)
        }

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("spore-voice-\(UUID().uuidString)")
            .appendingPathExtension("m4a")

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44_100,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue
        ]

        do {
            let recorder = try AVAudioRecorder(url: url, settings: settings)
            recorder.prepareToRecord()
            guard recorder.record() else {
                throw AudioRecordingError.recorderFailed("AVAudioRecorder.record() returned false")
            }
            self.recorder = recorder
            self.currentURL = url
            self.isRecording = true
        } catch let error as AudioRecordingError {
            throw error
        } catch {
            throw AudioRecordingError.recorderFailed(error.localizedDescription)
        }
    }

    func stop() async -> URL? {
        recorder?.stop()
        try? AVAudioSession.sharedInstance().setActive(false)
        isRecording = false
        let url = currentURL
        recorder = nil
        currentURL = nil
        return url
    }

    /// Wraps `AVAudioSession`'s permission API in async/await, supporting
    /// both the iOS 17+ `AVAudioApplication` API and the older session API.
    private func requestPermission(session: AVAudioSession) async -> Bool {
        switch session.recordPermission {
        case .granted:
            return true
        case .denied:
            return false
        case .undetermined:
            return await withCheckedContinuation { continuation in
                session.requestRecordPermission { granted in
                    continuation.resume(returning: granted)
                }
            }
        @unknown default:
            return false
        }
    }
}
