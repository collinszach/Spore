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

    /// An `AudioCaptureAPI` that never performs network I/O — used in previews.
    struct NoopAudioAPI: AudioCaptureAPI {
        func sendAudio(captureUUID: UUID, fileURL: URL, source: String) async throws {
            // Intentionally does nothing.
        }
    }

    /// An `AudioRecording` that does nothing — used in previews.
    final class NoopRecorder: AudioRecording, @unchecked Sendable {
        private(set) var isRecording = false

        func start() async throws {
            isRecording = true
        }

        func stop() async -> URL? {
            isRecording = false
            return nil
        }
    }
}

/// A `SporeAPI` returning canned Review/Pipeline data — used in previews.
struct PreviewSporeAPI: SporeAPI {
    func fetchReviewQueue() async throws -> [ReviewItemDTO] {
        [
            ReviewItemDTO(
                id: UUID(),
                captureID: UUID(),
                reason: "New domain detected: woodworking",
                status: "open",
                suggestedPath: "domains/woodworking/jig-ideas.md",
                suggestedType: "project",
                confidence: 0.62,
                createdAt: .now,
                resolvedAt: nil
            ),
            ReviewItemDTO(
                id: UUID(),
                captureID: UUID(),
                reason: "Looks like a fleeting note",
                status: "open",
                suggestedPath: "inbox/2026-06-13-thought.md",
                suggestedType: "fleeting",
                confidence: 0.41,
                createdAt: .now,
                resolvedAt: nil
            ),
        ]
    }

    func act(reviewID: UUID, action: ReviewAction, redirect: RedirectPayload?, merge: MergePayload?) async throws -> ReviewItemDTO {
        ReviewItemDTO(
            id: reviewID,
            captureID: nil,
            reason: nil,
            status: action == .discard ? "discarded" : "resolved",
            suggestedPath: nil,
            suggestedType: nil,
            confidence: nil,
            createdAt: .now,
            resolvedAt: .now
        )
    }

    func fetchPipeline() async throws -> PipelineDTO {
        PipelineDTO(
            states: [
                "seedling": [
                    PipelineNoteDTO(id: UUID(), title: "Garden bed layout", type: "project", ideaState: "seedling", domain: "garden", updatedAt: .now),
                ],
                "sapling": [
                    PipelineNoteDTO(id: UUID(), title: "Workshop dust collection", type: "project", ideaState: "sapling", domain: "woodworking", updatedAt: .now),
                ],
                "project": [
                    PipelineNoteDTO(id: UUID(), title: "Spore iOS app", type: "project", ideaState: "project", domain: "spore", updatedAt: .now),
                ],
            ],
            counts: ["seedling": 1, "sapling": 1, "sprout": 0, "project": 1, "shipped": 0, "archived": 0]
        )
    }

    func moveNote(id: UUID, to state: String) async throws -> PipelineNoteDTO {
        PipelineNoteDTO(id: id, title: nil, type: nil, ideaState: state, domain: nil, updatedAt: .now)
    }
}
