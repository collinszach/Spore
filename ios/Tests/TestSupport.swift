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

/// A single recorded call to `MockSporeAPI.act`.
struct RecordedAction: Equatable {
    let reviewID: UUID
    let action: ReviewAction
    let redirect: RedirectPayload?
    let merge: MergePayload?

    static func == (lhs: RecordedAction, rhs: RecordedAction) -> Bool {
        lhs.reviewID == rhs.reviewID
            && lhs.action == rhs.action
            && lhs.redirect == rhs.redirect
            && lhs.merge == rhs.merge
    }
}

extension RedirectPayload: @retroactive Equatable {
    public static func == (lhs: RedirectPayload, rhs: RedirectPayload) -> Bool {
        lhs.type == rhs.type && lhs.domain == rhs.domain && lhs.tags == rhs.tags && lhs.suggestedPath == rhs.suggestedPath
    }
}

extension MergePayload: @retroactive Equatable {
    public static func == (lhs: MergePayload, rhs: MergePayload) -> Bool {
        lhs.targetNoteID == rhs.targetNoteID
    }
}

/// Mock `SporeAPI` for testing Review/Pipeline view models — can be
/// configured to return canned data and/or throw, and records every call.
final class MockSporeAPI: SporeAPI, @unchecked Sendable {
    var reviewQueue: [ReviewItemDTO] = []
    var pipeline = PipelineDTO(states: [:], counts: [:])

    var shouldFailFetchReview = false
    var shouldFailAct = false
    var shouldFailFetchPipeline = false
    var shouldFailMove = false

    private(set) var actedReviewIDs: [RecordedAction] = []
    private(set) var movedNoteIDs: [(id: UUID, state: String)] = []

    func fetchReviewQueue() async throws -> [ReviewItemDTO] {
        if shouldFailFetchReview {
            throw SporeAPIError.server(status: 500)
        }
        return reviewQueue
    }

    func act(reviewID: UUID, action: ReviewAction, redirect: RedirectPayload?, merge: MergePayload?) async throws -> ReviewItemDTO {
        actedReviewIDs.append(RecordedAction(reviewID: reviewID, action: action, redirect: redirect, merge: merge))
        if shouldFailAct {
            throw SporeAPIError.server(status: 500)
        }
        return ReviewItemDTO(
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
        if shouldFailFetchPipeline {
            throw SporeAPIError.server(status: 500)
        }
        return pipeline
    }

    func moveNote(id: UUID, to state: String) async throws -> PipelineNoteDTO {
        movedNoteIDs.append((id: id, state: state))
        if shouldFailMove {
            throw SporeAPIError.server(status: 500)
        }
        return PipelineNoteDTO(id: id, title: nil, type: nil, ideaState: state, domain: nil, updatedAt: .now)
    }
}
