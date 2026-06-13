import Foundation
import SwiftData

/// Persistence seam for `CaptureQueue`. Abstracts away SwiftData so the
/// queue's sync/backoff/idempotency logic can be tested in-memory.
@MainActor
protocol CaptureStore: AnyObject {
    /// Persists a new capture immediately (no network I/O).
    func insert(_ capture: QueuedCapture)

    /// All captures that have not yet synced to the backend.
    func unsynced() -> [QueuedCapture]

    /// Marks a capture as synced at the given date and clears its last error.
    func markSynced(id: UUID, at date: Date)

    /// Records a failed sync attempt: increments `attemptCount` and sets `lastError`.
    func recordFailure(id: UUID, error: String)
}

/// Production `CaptureStore` backed by SwiftData. This is the ONLY place
/// `CaptureQueueItem` (the `@Model`) is touched.
@MainActor
final class SwiftDataCaptureStore: CaptureStore {
    private let modelContext: ModelContext

    init(modelContext: ModelContext) {
        self.modelContext = modelContext
    }

    func insert(_ capture: QueuedCapture) {
        let item = CaptureQueueItem(
            id: capture.id,
            body: capture.body,
            source: capture.source,
            createdAt: capture.createdAt,
            syncedAt: capture.syncedAt,
            attemptCount: capture.attemptCount,
            lastError: capture.lastError
        )
        modelContext.insert(item)
        try? modelContext.save()
    }

    func unsynced() -> [QueuedCapture] {
        let descriptor = FetchDescriptor<CaptureQueueItem>(
            predicate: #Predicate { $0.syncedAt == nil }
        )
        guard let items = try? modelContext.fetch(descriptor) else { return [] }
        return items.map { item in
            QueuedCapture(
                id: item.id,
                body: item.body,
                source: item.source,
                createdAt: item.createdAt,
                syncedAt: item.syncedAt,
                attemptCount: item.attemptCount,
                lastError: item.lastError
            )
        }
    }

    func markSynced(id: UUID, at date: Date) {
        guard let item = fetchItem(id: id) else { return }
        item.syncedAt = date
        item.lastError = nil
        try? modelContext.save()
    }

    func recordFailure(id: UUID, error: String) {
        guard let item = fetchItem(id: id) else { return }
        item.attemptCount += 1
        item.lastError = error
        try? modelContext.save()
    }

    private func fetchItem(id: UUID) -> CaptureQueueItem? {
        let descriptor = FetchDescriptor<CaptureQueueItem>(
            predicate: #Predicate { $0.id == id }
        )
        return try? modelContext.fetch(descriptor).first
    }
}

/// In-memory `CaptureStore` for tests and previews. No SwiftData involved.
@MainActor
final class InMemoryCaptureStore: CaptureStore {
    private(set) var captures: [QueuedCapture] = []

    init(captures: [QueuedCapture] = []) {
        self.captures = captures
    }

    func insert(_ capture: QueuedCapture) {
        captures.append(capture)
    }

    func unsynced() -> [QueuedCapture] {
        captures.filter { $0.syncedAt == nil }
    }

    func markSynced(id: UUID, at date: Date) {
        guard let index = captures.firstIndex(where: { $0.id == id }) else { return }
        captures[index].syncedAt = date
        captures[index].lastError = nil
    }

    func recordFailure(id: UUID, error: String) {
        guard let index = captures.firstIndex(where: { $0.id == id }) else { return }
        captures[index].attemptCount += 1
        captures[index].lastError = error
    }
}
