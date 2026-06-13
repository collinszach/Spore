import Foundation

/// ViewModel for the Pipeline tab (Epic 7).
///
/// Loads `/pipeline` and exposes notes grouped by `idea_state` in the
/// canonical pipeline order, plus per-state counts.
@MainActor
@Observable
final class PipelineViewModel {
    /// Canonical pipeline order: seedling -> sapling -> sprout -> project -> shipped -> archived.
    static let stateOrder: [String] = [
        "seedling", "sapling", "sprout", "project", "shipped", "archived",
    ]

    private(set) var notesByState: [String: [PipelineNoteDTO]] = [:]
    private(set) var counts: [String: Int] = [:]
    var errorMessage: String?
    private(set) var isLoading = false

    private let api: SporeAPI

    init(api: SporeAPI) {
        self.api = api
    }

    /// States in canonical order, including any unexpected states returned
    /// by the server (appended after the known ones).
    var orderedStates: [String] {
        let known = Self.stateOrder.filter { notesByState[$0] != nil }
        let extra = notesByState.keys.filter { !Self.stateOrder.contains($0) }.sorted()
        return known + extra
    }

    func notes(for state: String) -> [PipelineNoteDTO] {
        notesByState[state] ?? []
    }

    func count(for state: String) -> Int {
        counts[state] ?? notesByState[state]?.count ?? 0
    }

    var isEmpty: Bool {
        notesByState.values.allSatisfy { $0.isEmpty }
    }

    /// Loads (or reloads) the pipeline board.
    func load() async {
        isLoading = true
        errorMessage = nil
        do {
            let pipeline = try await api.fetchPipeline()
            notesByState = pipeline.states
            counts = pipeline.counts
        } catch {
            errorMessage = Self.message(for: error)
        }
        isLoading = false
    }

    /// Moves a note to a new idea_state and refreshes the board on success.
    func move(_ note: PipelineNoteDTO, to state: String) async {
        errorMessage = nil
        do {
            _ = try await api.moveNote(id: note.id, to: state)
            await load()
        } catch {
            errorMessage = Self.message(for: error)
        }
    }

    private static func message(for error: Error) -> String {
        switch error {
        case SporeAPIError.notConfigured:
            return "Spore isn't configured yet. Set the API URL in Settings."
        case SporeAPIError.server(let status):
            return "Server error (\(status))."
        case SporeAPIError.api(let message):
            return message
        case SporeAPIError.transport(let message):
            return "Network error: \(message)"
        case SporeAPIError.decoding(let message):
            return "Couldn't read server response: \(message)"
        default:
            return error.localizedDescription
        }
    }
}
