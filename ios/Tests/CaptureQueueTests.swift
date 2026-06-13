import XCTest
import SwiftData
@testable import Spore

@MainActor
final class CaptureQueueTests: XCTestCase {
    func testEnqueuePersistsImmediately() throws {
        let context = try TestSupport.makeContext()
        let queue = CaptureQueue(modelContext: context, api: MockCaptureAPI())

        let id = queue.enqueue(body: "hello world")

        let items = try context.fetch(FetchDescriptor<CaptureQueueItem>())
        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(items.first?.id, id)
        XCTAssertEqual(items.first?.body, "hello world")
        XCTAssertNil(items.first?.syncedAt)
    }

    func testDrainMarksSyncedOnSuccess() async throws {
        let context = try TestSupport.makeContext()
        let api = MockCaptureAPI(shouldFail: false)
        let queue = CaptureQueue(modelContext: context, api: api)

        let id = queue.enqueue(body: "sync me")
        await queue.drain()

        let items = try context.fetch(FetchDescriptor<CaptureQueueItem>())
        let item = items.first { $0.id == id }
        XCTAssertNotNil(item?.syncedAt)
        XCTAssertEqual(item?.attemptCount, 0)
    }

    func testDrainFailureLeavesUnsyncedAndIncrementsAttempt() async throws {
        let context = try TestSupport.makeContext()
        let api = MockCaptureAPI(shouldFail: true)
        let queue = CaptureQueue(modelContext: context, api: api)

        let id = queue.enqueue(body: "offline capture")
        await queue.drain()

        let items = try context.fetch(FetchDescriptor<CaptureQueueItem>())
        let item = items.first { $0.id == id }
        XCTAssertNil(item?.syncedAt)
        XCTAssertEqual(item?.attemptCount, 1)
        XCTAssertNotNil(item?.lastError)
    }

    func testReDrainAfterComingOnlineSyncs() async throws {
        let context = try TestSupport.makeContext()
        let api = MockCaptureAPI(shouldFail: true)
        let queue = CaptureQueue(modelContext: context, api: api)

        let id = queue.enqueue(body: "retry me")
        await queue.drain() // fails

        api.shouldFail = false
        await queue.drain() // now succeeds

        let items = try context.fetch(FetchDescriptor<CaptureQueueItem>())
        let item = items.first { $0.id == id }
        XCTAssertNotNil(item?.syncedAt)
        XCTAssertEqual(item?.attemptCount, 1)
    }

    func testAlreadySyncedItemIsNotRePosted() async throws {
        let context = try TestSupport.makeContext()
        let api = MockCaptureAPI(shouldFail: false)
        let queue = CaptureQueue(modelContext: context, api: api)

        let id = queue.enqueue(body: "once")
        await queue.drain()
        XCTAssertEqual(api.postedUUIDs.filter { $0 == id }.count, 1)

        await queue.drain() // should be a no-op for already-synced items

        XCTAssertEqual(api.postedUUIDs.filter { $0 == id }.count, 1)
    }

    func testTwoEnqueuesCreateDistinctUUIDs() throws {
        let context = try TestSupport.makeContext()
        let queue = CaptureQueue(modelContext: context, api: MockCaptureAPI())

        let id1 = queue.enqueue(body: "first")
        let id2 = queue.enqueue(body: "second")

        XCTAssertNotEqual(id1, id2)

        let items = try context.fetch(FetchDescriptor<CaptureQueueItem>())
        XCTAssertEqual(items.count, 2)
    }
}
