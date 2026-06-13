import XCTest
@testable import Spore

@MainActor
final class CaptureQueueTests: XCTestCase {
    func testEnqueuePersistsImmediately() {
        let store = InMemoryCaptureStore()
        let queue = CaptureQueue(store: store, api: MockCaptureAPI())

        let id = queue.enqueue(body: "hello world")

        XCTAssertEqual(store.captures.count, 1)
        XCTAssertEqual(store.captures.first?.id, id)
        XCTAssertEqual(store.captures.first?.body, "hello world")
        XCTAssertNil(store.captures.first?.syncedAt)
    }

    func testDrainMarksSyncedOnSuccess() async {
        let store = InMemoryCaptureStore()
        let api = MockCaptureAPI(shouldFail: false)
        let queue = CaptureQueue(store: store, api: api)

        let id = queue.enqueue(body: "sync me")
        await queue.drain()

        let item = store.captures.first { $0.id == id }
        XCTAssertNotNil(item?.syncedAt)
        XCTAssertEqual(item?.attemptCount, 0)
    }

    func testDrainFailureLeavesUnsyncedAndIncrementsAttempt() async {
        let store = InMemoryCaptureStore()
        let api = MockCaptureAPI(shouldFail: true)
        let queue = CaptureQueue(store: store, api: api)

        let id = queue.enqueue(body: "offline capture")
        await queue.drain()

        let item = store.captures.first { $0.id == id }
        XCTAssertNil(item?.syncedAt)
        XCTAssertEqual(item?.attemptCount, 1)
        XCTAssertNotNil(item?.lastError)
    }

    func testReDrainAfterComingOnlineSyncs() async {
        let store = InMemoryCaptureStore()
        let api = MockCaptureAPI(shouldFail: true)
        let queue = CaptureQueue(store: store, api: api)

        let id = queue.enqueue(body: "retry me")
        await queue.drain() // fails

        api.shouldFail = false
        await queue.drain() // now succeeds

        let item = store.captures.first { $0.id == id }
        XCTAssertNotNil(item?.syncedAt)
        XCTAssertEqual(item?.attemptCount, 1)
    }

    func testAlreadySyncedItemIsNotRePosted() async {
        let store = InMemoryCaptureStore()
        let api = MockCaptureAPI(shouldFail: false)
        let queue = CaptureQueue(store: store, api: api)

        let id = queue.enqueue(body: "once")
        await queue.drain()
        XCTAssertEqual(api.postedUUIDs.filter { $0 == id }.count, 1)

        await queue.drain() // should be a no-op for already-synced items

        XCTAssertEqual(api.postedUUIDs.filter { $0 == id }.count, 1)
    }

    func testTwoEnqueuesCreateDistinctUUIDs() {
        let store = InMemoryCaptureStore()
        let queue = CaptureQueue(store: store, api: MockCaptureAPI())

        let id1 = queue.enqueue(body: "first")
        let id2 = queue.enqueue(body: "second")

        XCTAssertNotEqual(id1, id2)
        XCTAssertEqual(store.captures.count, 2)
    }

    func testBackoffDelayGrowsExponentially() async {
        // CaptureQueue.drain() itself doesn't gate on backoff — callers that
        // schedule retries use `backoffDelay(for:)` to decide whether to call
        // `drain()` again. This verifies that contract: after one failed
        // attempt, the next retry isn't scheduled for ~1 minute.
        let store = InMemoryCaptureStore()
        let api = MockCaptureAPI(shouldFail: true)
        let queue = CaptureQueue(store: store, api: api, baseBackoff: 60)

        let id = queue.enqueue(body: "flaky")
        await queue.drain() // attemptCount becomes 1

        let item = store.captures.first { $0.id == id }
        XCTAssertEqual(item?.attemptCount, 1)

        let delay = queue.backoffDelay(for: item!.attemptCount)
        XCTAssertEqual(delay, 60) // 1x baseBackoff

        let delayAfterTwo = queue.backoffDelay(for: 2)
        XCTAssertEqual(delayAfterTwo, 120) // 2x baseBackoff
    }
}
