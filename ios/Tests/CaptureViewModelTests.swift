import XCTest
@testable import Spore

@MainActor
final class CaptureViewModelTests: XCTestCase {
    func testSubmitEnqueuesAndClearsDraft() {
        let store = InMemoryCaptureStore()
        let queue = CaptureQueue(store: store, api: MockCaptureAPI())
        let viewModel = CaptureViewModel(queue: queue)

        viewModel.draft = "  a fleeting thought  "
        let id = viewModel.submit()

        XCTAssertNotNil(id)
        XCTAssertEqual(viewModel.draft, "")

        XCTAssertEqual(store.captures.count, 1)
        XCTAssertEqual(store.captures.first?.body, "a fleeting thought")
    }

    func testSubmitWithEmptyDraftDoesNothing() {
        let store = InMemoryCaptureStore()
        let queue = CaptureQueue(store: store, api: MockCaptureAPI())
        let viewModel = CaptureViewModel(queue: queue)

        viewModel.draft = "   "
        let id = viewModel.submit()

        XCTAssertNil(id)
        XCTAssertEqual(viewModel.draft, "   ")
        XCTAssertEqual(store.captures.count, 0)
    }

    func testCanSubmitReflectsDraftState() {
        let store = InMemoryCaptureStore()
        let queue = CaptureQueue(store: store, api: MockCaptureAPI())
        let viewModel = CaptureViewModel(queue: queue)

        XCTAssertFalse(viewModel.canSubmit)
        viewModel.draft = "something"
        XCTAssertTrue(viewModel.canSubmit)
        viewModel.draft = "   "
        XCTAssertFalse(viewModel.canSubmit)
    }
}
