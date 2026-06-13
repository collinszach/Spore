import XCTest
@testable import Spore

@MainActor
final class CaptureIntentTests: XCTestCase {
    override func tearDown() {
        CaptureIntent.serviceProvider = { CaptureService.shared() }
        super.tearDown()
    }

    func testPerformEnqueuesCaptureWithSiriSource() async throws {
        let store = InMemoryCaptureStore()
        let queue = CaptureQueue(store: store, api: MockCaptureAPI())
        CaptureIntent.serviceProvider = { CaptureService(queue: queue) }

        let intent = CaptureIntent(text: "remember to water the plants")
        _ = try await intent.perform()

        XCTAssertEqual(store.captures.count, 1)
        XCTAssertEqual(store.captures.first?.body, "remember to water the plants")
        XCTAssertEqual(store.captures.first?.source, "siri")
        XCTAssertNil(store.captures.first?.syncedAt)
    }

    func testPerformWithEmptyTextDoesNotEnqueue() async throws {
        let store = InMemoryCaptureStore()
        let queue = CaptureQueue(store: store, api: MockCaptureAPI())
        CaptureIntent.serviceProvider = { CaptureService(queue: queue) }

        let intent = CaptureIntent(text: "   ")
        _ = try await intent.perform()

        XCTAssertEqual(store.captures.count, 0)
    }
}
