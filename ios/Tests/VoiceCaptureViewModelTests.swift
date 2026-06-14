import XCTest
@testable import Spore

@MainActor
final class VoiceCaptureViewModelTests: XCTestCase {
    func testStartSetsIsRecording() async throws {
        let recorder = MockAudioRecording()
        let api = MockAudioCaptureAPI()
        let viewModel = VoiceCaptureViewModel(recorder: recorder, api: api)

        XCTAssertFalse(viewModel.isRecording)
        try await viewModel.start()
        XCTAssertTrue(viewModel.isRecording)
        XCTAssertEqual(recorder.startCallCount, 1)
    }

    func testStopUploadsRecordingWithVoiceSource() async throws {
        let recorder = MockAudioRecording()
        let api = MockAudioCaptureAPI()
        let viewModel = VoiceCaptureViewModel(recorder: recorder, api: api)

        try await viewModel.start()
        let captureID = await viewModel.stop()

        XCTAssertFalse(viewModel.isRecording)
        XCTAssertNotNil(captureID)
        XCTAssertEqual(api.sentUploads.count, 1)
        XCTAssertEqual(api.sentUploads.first?.captureUUID, captureID)
        XCTAssertEqual(api.sentUploads.first?.source, "ios_voice")
        XCTAssertEqual(api.sentUploads.first?.fileURL, recorder.fileURL)
        XCTAssertTrue(viewModel.pending.isEmpty)
        XCTAssertNil(viewModel.lastError)
    }

    func testStopWithNoFileDoesNothing() async throws {
        let recorder = MockAudioRecording(fileURL: nil)
        let api = MockAudioCaptureAPI()
        let viewModel = VoiceCaptureViewModel(recorder: recorder, api: api)

        try await viewModel.start()
        let captureID = await viewModel.stop()

        XCTAssertNil(captureID)
        XCTAssertTrue(api.sentUploads.isEmpty)
        XCTAssertTrue(viewModel.pending.isEmpty)
    }

    func testFailedUploadKeepsPendingAndSurfacesError() async throws {
        let recorder = MockAudioRecording()
        let api = MockAudioCaptureAPI(shouldFail: true)
        let viewModel = VoiceCaptureViewModel(recorder: recorder, api: api)

        try await viewModel.start()
        let captureID = await viewModel.stop()

        XCTAssertNotNil(captureID)
        XCTAssertEqual(viewModel.pending.count, 1)
        XCTAssertEqual(viewModel.pending.first?.id, captureID)
        XCTAssertEqual(viewModel.pending.first?.fileURL, recorder.fileURL)
        XCTAssertEqual(viewModel.pending.first?.source, "ios_voice")
        XCTAssertNotNil(viewModel.lastError)
    }

    func testRetryPendingClearsPendingOnSuccess() async throws {
        let recorder = MockAudioRecording()
        let api = MockAudioCaptureAPI(shouldFail: true)
        let viewModel = VoiceCaptureViewModel(recorder: recorder, api: api)

        try await viewModel.start()
        let captureID = await viewModel.stop()
        XCTAssertEqual(viewModel.pending.count, 1)

        // Reconnect: subsequent uploads now succeed.
        api.shouldFail = false
        await viewModel.retryPending()

        XCTAssertTrue(viewModel.pending.isEmpty)
        XCTAssertNil(viewModel.lastError)
        XCTAssertEqual(api.sentUploads.count, 2)
        XCTAssertEqual(api.sentUploads.last?.captureUUID, captureID)
    }

    func testRetryPendingWithStillFailingUploadKeepsPending() async throws {
        let recorder = MockAudioRecording()
        let api = MockAudioCaptureAPI(shouldFail: true)
        let viewModel = VoiceCaptureViewModel(recorder: recorder, api: api)

        try await viewModel.start()
        _ = await viewModel.stop()
        XCTAssertEqual(viewModel.pending.count, 1)

        await viewModel.retryPending()

        XCTAssertEqual(viewModel.pending.count, 1)
        XCTAssertNotNil(viewModel.lastError)
    }

    func testStartPermissionDeniedDoesNotSetIsRecording() async {
        let recorder = MockAudioRecording()
        recorder.startError = AudioRecordingError.permissionDenied
        let api = MockAudioCaptureAPI()
        let viewModel = VoiceCaptureViewModel(recorder: recorder, api: api)

        do {
            try await viewModel.start()
            XCTFail("expected permission denied error")
        } catch {
            XCTAssertEqual(error as? AudioRecordingError, .permissionDenied)
        }

        XCTAssertFalse(viewModel.isRecording)
    }
}
