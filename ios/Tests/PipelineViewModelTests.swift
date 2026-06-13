import XCTest
@testable import Spore

@MainActor
final class PipelineViewModelTests: XCTestCase {
    private func makeNote(state: String) -> PipelineNoteDTO {
        PipelineNoteDTO(id: UUID(), title: "Note", type: "project", ideaState: state, domain: "spore", updatedAt: .now)
    }

    func testLoadGroupsNotesByStateWithCounts() async {
        let api = MockSporeAPI()
        api.pipeline = PipelineDTO(
            states: [
                "seedling": [makeNote(state: "seedling"), makeNote(state: "seedling")],
                "sapling": [makeNote(state: "sapling")],
            ],
            counts: ["seedling": 2, "sapling": 1, "sprout": 0, "project": 0, "shipped": 0, "archived": 0]
        )
        let viewModel = PipelineViewModel(api: api)

        await viewModel.load()

        XCTAssertEqual(viewModel.notes(for: "seedling").count, 2)
        XCTAssertEqual(viewModel.notes(for: "sapling").count, 1)
        XCTAssertEqual(viewModel.count(for: "seedling"), 2)
        XCTAssertEqual(viewModel.count(for: "sapling"), 1)
        XCTAssertEqual(viewModel.count(for: "sprout"), 0)
        XCTAssertNil(viewModel.errorMessage)
        XCTAssertFalse(viewModel.isEmpty)
    }

    func testOrderedStatesFollowsCanonicalPipelineOrder() async {
        let api = MockSporeAPI()
        api.pipeline = PipelineDTO(
            states: [
                "archived": [makeNote(state: "archived")],
                "seedling": [makeNote(state: "seedling")],
                "project": [makeNote(state: "project")],
            ],
            counts: [:]
        )
        let viewModel = PipelineViewModel(api: api)

        await viewModel.load()

        XCTAssertEqual(viewModel.orderedStates, ["seedling", "project", "archived"])
    }

    func testLoadFailureSurfacesError() async {
        let api = MockSporeAPI()
        api.shouldFailFetchPipeline = true
        let viewModel = PipelineViewModel(api: api)

        await viewModel.load()

        XCTAssertNotNil(viewModel.errorMessage)
        XCTAssertTrue(viewModel.isEmpty)
    }

    func testEmptyPipelineIsEmpty() async {
        let api = MockSporeAPI()
        api.pipeline = PipelineDTO(states: ["seedling": []], counts: ["seedling": 0])
        let viewModel = PipelineViewModel(api: api)

        await viewModel.load()

        XCTAssertTrue(viewModel.isEmpty)
    }
}
