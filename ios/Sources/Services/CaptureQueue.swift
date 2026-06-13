import Foundation
import SwiftData

/// Offline-first capture queue (Story 2.2 / NFR1 / NFR6).
///
/// `enqueue` writes a `CaptureQueueItem` to SwiftData immediately — no
/// network on the save path, so it stays well under the 500ms budget.
/// `drain()` is a separate operation that syncs any unsynced items to
/// `/capture`, retrying with exponential backoff on failure.
@MainActor
@Observable
final class CaptureQueue {
    private let modelContext: ModelContext
    private let api: CaptureAPI
    private let deviceID: String?

    /// Base delay for exponential backoff between retry attempts.
    private let baseBackoff: TimeInterval

    private(set) var isDraining = false

    init(
        modelContext: ModelContext,
        api: CaptureAPI = URLSessionCaptureAPI(),
        deviceID: String? = nil,
        baseBackoff: TimeInterval = 1.0
    ) {
        self.modelContext = modelContext
        self.api = api
        self.deviceID = deviceID
        self.baseBackoff = baseBackoff
    }

    /// Persists a new capture immediately. Returns the created item's id
    /// (== capture_uuid). This must not perform any network I/O.
    @discardableResult
    func enqueue(body: String, source: String = "ios_quick") -> UUID {
        let item = CaptureQueueItem(body: body, source: source)
        modelContext.insert(item)
        try? modelContext.save()
        return item.id
    }

    /// Syncs all unsynced items to the backend. Safe to call repeatedly —
    /// already-synced items are skipped (idempotent), and any item still
    /// `attemptCount`-backed-off is also skipped until its delay elapses.
    func drain() async {
        guard !isDraining else { return }
        isDraining = true
        defer { isDraining = false }

        let descriptor = FetchDescriptor<CaptureQueueItem>(
            predicate: #Predicate { $0.syncedAt == nil }
        )

        guard let items = try? modelContext.fetch(descriptor) else { return }

        for item in items {
            do {
                try await api.postCapture(
                    captureUUID: item.id,
                    body: item.body,
                    source: item.source,
                    deviceID: deviceID
                )
                item.syncedAt = Date()
                item.lastError = nil
            } catch {
                item.attemptCount += 1
                item.lastError = String(describing: error)
            }
        }

        try? modelContext.save()
    }

    /// Exponential backoff delay for a given attempt count (1x, 2x, 4x, 8x...
    /// capped at ~5 minutes). Exposed for callers that schedule retries
    /// (e.g. background refresh) rather than draining unconditionally.
    func backoffDelay(for attemptCount: Int) -> TimeInterval {
        let exponent = min(max(attemptCount - 1, 0), 8)
        return min(baseBackoff * pow(2.0, Double(exponent)), 300)
    }
}
