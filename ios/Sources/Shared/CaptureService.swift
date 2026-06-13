import Foundation
import SwiftData

/// Thin enqueue seam shared by the app, `CaptureIntent` (Siri/Shortcuts), and
/// the Share Extension. Wraps a `CaptureQueue` so callers (especially App
/// Intents) can inject an `InMemoryCaptureStore` in tests without touching
/// SwiftData (Story 2.4).
@MainActor
struct CaptureService {
    let queue: CaptureQueue

    init(queue: CaptureQueue) {
        self.queue = queue
    }

    /// Builds a `CaptureService` backed by the shared App Group SwiftData
    /// store — used by the production app, intents, and extensions.
    static func shared() -> CaptureService {
        let container = AppGroup.makeSharedModelContainer()
        let store = SwiftDataCaptureStore(modelContext: container.mainContext)
        return CaptureService(queue: CaptureQueue(store: store))
    }

    /// Enqueues a capture with the given source and returns its id.
    @discardableResult
    func enqueue(body: String, source: String) -> UUID? {
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return queue.enqueue(body: trimmed, source: source)
    }
}
