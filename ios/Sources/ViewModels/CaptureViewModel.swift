import Foundation
import SwiftUI

/// ViewModel for the Capture screen (Story 2.1 / 2.2).
///
/// Holds the in-progress draft and delegates persistence to `CaptureQueue`.
/// `submit()` must be instant (<500ms) — it never waits on network.
@MainActor
@Observable
final class CaptureViewModel {
    var draft: String = ""

    private let queue: CaptureQueue

    init(queue: CaptureQueue) {
        self.queue = queue
    }

    /// Whether the current draft can be submitted.
    var canSubmit: Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// Enqueues the draft as a new capture and clears it for the next thought.
    /// Returns the new capture's id, or nil if the draft was empty.
    @discardableResult
    func submit() -> UUID? {
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        let id = queue.enqueue(body: trimmed)
        draft = ""
        return id
    }

    /// Kicks off a background sync attempt; safe to call without awaiting.
    func drainQueue() {
        Task {
            await queue.drain()
        }
    }
}
