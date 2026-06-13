import XCTest
@testable import Spore

@MainActor
final class ReviewViewModelTests: XCTestCase {
    private func makeItem(id: UUID = UUID()) -> ReviewItemDTO {
        ReviewItemDTO(
            id: id,
            captureID: UUID(),
            reason: "New domain detected",
            status: "open",
            suggestedPath: "inbox/note.md",
            suggestedType: "fleeting",
            confidence: 0.5,
            createdAt: .now,
            resolvedAt: nil
        )
    }

    func testLoadPopulatesItems() async {
        let api = MockSporeAPI()
        api.reviewQueue = [makeItem(), makeItem()]
        let viewModel = ReviewViewModel(api: api)

        await viewModel.load()

        XCTAssertEqual(viewModel.items.count, 2)
        XCTAssertFalse(viewModel.isEmpty)
        XCTAssertNil(viewModel.errorMessage)
    }

    func testLoadFailureSurfacesError() async {
        let api = MockSporeAPI()
        api.shouldFailFetchReview = true
        let viewModel = ReviewViewModel(api: api)

        await viewModel.load()

        XCTAssertTrue(viewModel.items.isEmpty)
        XCTAssertNotNil(viewModel.errorMessage)
    }

    func testApproveCallsAPIAndRemovesItem() async {
        let api = MockSporeAPI()
        let item = makeItem()
        api.reviewQueue = [item]
        let viewModel = ReviewViewModel(api: api)
        await viewModel.load()

        await viewModel.approve(item)

        XCTAssertTrue(viewModel.items.isEmpty)
        XCTAssertEqual(api.actedReviewIDs.count, 1)
        XCTAssertEqual(api.actedReviewIDs.first?.reviewID, item.id)
        XCTAssertEqual(api.actedReviewIDs.first?.action, .approve)
        XCTAssertNil(viewModel.errorMessage)
    }

    func testDiscardCallsAPIAndRemovesItem() async {
        let api = MockSporeAPI()
        let item = makeItem()
        api.reviewQueue = [item]
        let viewModel = ReviewViewModel(api: api)
        await viewModel.load()

        await viewModel.discard(item)

        XCTAssertTrue(viewModel.items.isEmpty)
        XCTAssertEqual(api.actedReviewIDs.first?.action, .discard)
    }

    func testFailingApproveRestoresItemAndSurfacesError() async {
        let api = MockSporeAPI()
        let item = makeItem()
        api.reviewQueue = [item]
        api.shouldFailAct = true
        let viewModel = ReviewViewModel(api: api)
        await viewModel.load()

        await viewModel.approve(item)

        XCTAssertEqual(viewModel.items.count, 1)
        XCTAssertEqual(viewModel.items.first?.id, item.id)
        XCTAssertNotNil(viewModel.errorMessage)
    }

    func testRedirectSendsPayload() async {
        let api = MockSporeAPI()
        let item = makeItem()
        api.reviewQueue = [item]
        let viewModel = ReviewViewModel(api: api)
        await viewModel.load()

        let payload = RedirectPayload(type: "project", domain: nil, tags: nil, suggestedPath: nil)
        await viewModel.redirect(item, payload: payload)

        XCTAssertTrue(viewModel.items.isEmpty)
        XCTAssertEqual(api.actedReviewIDs.first?.action, .redirect)
        XCTAssertEqual(api.actedReviewIDs.first?.redirect?.type, "project")
    }

    func testMergeSendsTargetNoteID() async {
        let api = MockSporeAPI()
        let item = makeItem()
        api.reviewQueue = [item]
        let viewModel = ReviewViewModel(api: api)
        await viewModel.load()

        let targetID = UUID()
        await viewModel.merge(item, targetNoteID: targetID)

        XCTAssertTrue(viewModel.items.isEmpty)
        XCTAssertEqual(api.actedReviewIDs.first?.action, .merge)
        XCTAssertEqual(api.actedReviewIDs.first?.merge?.targetNoteID, targetID)
    }
}
