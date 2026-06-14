import Foundation

/// A voice recording awaiting upload to `/capture/audio` (Story 2.6).
///
/// The recorded `.m4a` file already lives on disk (in the temp directory) the
/// moment recording stops — `enqueue` never deletes it. If `sendAudio` fails
/// (e.g. offline), the file stays on disk and the pending record is kept so
/// `retryPending()` can re-upload it once connectivity returns (NFR6).
struct PendingVoiceCapture: Identifiable, Equatable {
    let id: UUID
    let fileURL: URL
    let source: String
}

/// ViewModel for in-app voice capture (Story 2.6).
///
/// `start()`/`stop()` drive the recording lifecycle via `AudioRecording`.
/// `stop()` immediately attempts to upload the recorded file via
/// `AudioCaptureAPI`. If the upload fails, the recording is kept as a
/// `PendingVoiceCapture` (file + capture_uuid) so it is not lost — callers
/// can retry via `retryPending()` (e.g. on `NetworkMonitor.onReconnect`).
@MainActor
@Observable
final class VoiceCaptureViewModel {
    private let recorder: AudioRecording
    private let api: AudioCaptureAPI

    /// Source tag sent to `/capture/audio` for in-app voice recordings.
    static let source = "ios_voice"

    private(set) var isRecording = false
    private(set) var isUploading = false
    private(set) var pending: [PendingVoiceCapture] = []
    private(set) var lastError: String?

    init(recorder: AudioRecording, api: AudioCaptureAPI) {
        self.recorder = recorder
        self.api = api
    }

    /// Starts recording. Throws if mic permission is denied or the recorder
    /// fails to start.
    func start() async throws {
        try await recorder.start()
        isRecording = true
        lastError = nil
    }

    /// Stops recording and attempts to upload the result immediately. If the
    /// upload fails, the recording is retained in `pending` for later retry
    /// and `lastError` is set. Returns the new capture's id, or `nil` if
    /// nothing was recorded.
    @discardableResult
    func stop() async -> UUID? {
        let fileURL = await recorder.stop()
        isRecording = false

        guard let fileURL else { return nil }

        let captureUUID = UUID()
        await upload(PendingVoiceCapture(id: captureUUID, fileURL: fileURL, source: Self.source))
        return captureUUID
    }

    /// Retries uploading every pending recording. Successful uploads are
    /// removed from `pending`; failures remain for the next retry.
    func retryPending() async {
        let items = pending
        for item in items {
            await upload(item)
        }
    }

    /// Uploads a single pending recording. On success, removes it from
    /// `pending` (adding it first if it wasn't already there is a no-op).
    /// On failure, ensures it's present in `pending` and sets `lastError`.
    private func upload(_ item: PendingVoiceCapture) async {
        isUploading = true
        defer { isUploading = false }

        do {
            try await api.sendAudio(captureUUID: item.id, fileURL: item.fileURL, source: item.source)
            pending.removeAll { $0.id == item.id }
            lastError = nil
        } catch {
            if !pending.contains(where: { $0.id == item.id }) {
                pending.append(item)
            }
            lastError = String(describing: error)
        }
    }
}
