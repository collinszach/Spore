import Foundation

/// ViewModel for the Review tab (Epic 4).
///
/// Loads the open review queue and applies actions (approve/redirect/merge/
/// discard) optimistically: the item is removed from `items` immediately,
/// and restored (with `errorMessage` set) if the API call fails.
@MainActor
@Observable
final class ReviewViewModel {
    private(set) var items: [ReviewItemDTO] = []
    var errorMessage: String?
    private(set) var isLoading = false

    private let api: SporeAPI

    init(api: SporeAPI) {
        self.api = api
    }

    var isEmpty: Bool {
        items.isEmpty
    }

    /// Loads (or reloads) the open review queue.
    func load() async {
        isLoading = true
        errorMessage = nil
        do {
            items = try await api.fetchReviewQueue()
        } catch {
            errorMessage = Self.message(for: error)
        }
        isLoading = false
    }

    /// Approves the item: removes it optimistically, restores on failure.
    func approve(_ item: ReviewItemDTO) async {
        await perform(item, action: .approve)
    }

    /// Discards the item: removes it optimistically, restores on failure.
    func discard(_ item: ReviewItemDTO) async {
        await perform(item, action: .discard)
    }

    /// Redirects the item with the given corrected fields.
    func redirect(_ item: ReviewItemDTO, payload: RedirectPayload) async {
        await perform(item, action: .redirect, redirect: payload)
    }

    /// Merges the item into the given target note.
    func merge(_ item: ReviewItemDTO, targetNoteID: UUID) async {
        await perform(item, action: .merge, merge: MergePayload(targetNoteID: targetNoteID))
    }

    private func perform(
        _ item: ReviewItemDTO,
        action: ReviewAction,
        redirect: RedirectPayload? = nil,
        merge: MergePayload? = nil
    ) async {
        errorMessage = nil

        guard let index = items.firstIndex(where: { $0.id == item.id }) else { return }
        let removed = items.remove(at: index)

        do {
            _ = try await api.act(reviewID: item.id, action: action, redirect: redirect, merge: merge)
        } catch {
            items.insert(removed, at: min(index, items.count))
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
