import Foundation
@testable import Spore

/// Mock `CaptureAPI` for testing — can be configured to succeed or throw.
final class MockCaptureAPI: CaptureAPI, @unchecked Sendable {
    var shouldFail: Bool
    private(set) var postedUUIDs: [UUID] = []

    init(shouldFail: Bool = false) {
        self.shouldFail = shouldFail
    }

    func postCapture(captureUUID: UUID, body: String, source: String, deviceID: String?) async throws {
        postedUUIDs.append(captureUUID)
        if shouldFail {
            throw CaptureAPIError.server(status: 500)
        }
    }
}
