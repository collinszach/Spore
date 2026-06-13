import Foundation
import SwiftData
@testable import Spore

/// Shared test helpers for an isolated SwiftData container.
///
/// `ModelConfiguration(isStoredInMemoryOnly: true)` triggers a SwiftData
/// fetch crash on this Xcode 26.4 toolchain (EXC_BREAKPOINT inside
/// SwiftData.framework on `ModelContext.fetch`), so tests instead use a
/// uniquely-named temporary file store, which is deleted automatically by
/// the OS and gives the same per-test isolation.
enum TestSupport {
    @MainActor
    static func makeContext() throws -> ModelContext {
        let schema = Schema([CaptureQueueItem.self])
        let url = URL.temporaryDirectory.appending(path: "spore-test-\(UUID().uuidString).store")
        let configuration = ModelConfiguration(schema: schema, url: url)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        return container.mainContext
    }
}

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
