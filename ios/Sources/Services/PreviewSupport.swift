import Foundation
import SwiftData

/// Shared helpers for SwiftUI previews — in-memory model container plus a
/// no-op API implementation so previews never touch the network.
enum PreviewSupport {
    static var container: ModelContainer = {
        let schema = Schema([CaptureQueueItem.self])
        let configuration = ModelConfiguration(isStoredInMemoryOnly: true)
        return try! ModelContainer(for: schema, configurations: [configuration])
    }()

    /// A `CaptureAPI` that never performs network I/O — used in previews.
    struct NoopAPI: CaptureAPI {
        func postCapture(captureUUID: UUID, body: String, source: String, deviceID: String?) async throws {
            // Intentionally does nothing.
        }
    }
}
