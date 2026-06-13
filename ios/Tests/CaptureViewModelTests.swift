import XCTest
import SwiftData
@testable import Spore

@MainActor
final class CaptureViewModelTests: XCTestCase {
    func testSubmitEnqueuesAndClearsDraft() throws {
        let context = try TestSupport.makeContext()
        let queue = CaptureQueue(modelContext: context, api: MockCaptureAPI())
        let viewModel = CaptureViewModel(queue: queue)

        viewModel.draft = "  a fleeting thought  "
        let id = viewModel.submit()

        XCTAssertNotNil(id)
        XCTAssertEqual(viewModel.draft, "")

        let items = try context.fetch(FetchDescriptor<CaptureQueueItem>())
        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(items.first?.body, "a fleeting thought")
    }

    func testSubmitWithEmptyDraftDoesNothing() throws {
        let context = try TestSupport.makeContext()
        let queue = CaptureQueue(modelContext: context, api: MockCaptureAPI())
        let viewModel = CaptureViewModel(queue: queue)

        viewModel.draft = "   "
        let id = viewModel.submit()

        XCTAssertNil(id)
        XCTAssertEqual(viewModel.draft, "   ")

        let items = try context.fetch(FetchDescriptor<CaptureQueueItem>())
        XCTAssertEqual(items.count, 0)
    }

    func testCanSubmitReflectsDraftState() throws {
        let context = try TestSupport.makeContext()
        let queue = CaptureQueue(modelContext: context, api: MockCaptureAPI())
        let viewModel = CaptureViewModel(queue: queue)

        XCTAssertFalse(viewModel.canSubmit)
        viewModel.draft = "something"
        XCTAssertTrue(viewModel.canSubmit)
        viewModel.draft = "   "
        XCTAssertFalse(viewModel.canSubmit)
    }
}
