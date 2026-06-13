import SwiftUI
import UIKit

/// The Review tab — works through the open review queue (Epic 4).
struct ReviewView: View {
    @State private var viewModel: ReviewViewModel
    @State private var redirectTarget: ReviewItemDTO?
    @State private var mergeTarget: ReviewItemDTO?

    init(viewModel: ReviewViewModel) {
        _viewModel = State(initialValue: viewModel)
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Review")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            Task { await viewModel.load() }
                        } label: {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                    }
                }
                .onAppear {
                    Task { await viewModel.load() }
                }
                .alert(
                    "Something went wrong",
                    isPresented: Binding(
                        get: { viewModel.errorMessage != nil },
                        set: { if !$0 { viewModel.errorMessage = nil } }
                    )
                ) {
                    Button("OK", role: .cancel) { viewModel.errorMessage = nil }
                } message: {
                    Text(viewModel.errorMessage ?? "")
                }
                .sheet(item: $redirectTarget) { item in
                    RedirectSheet(item: item) { payload in
                        Task { await viewModel.redirect(item, payload: payload) }
                    }
                }
                .sheet(item: $mergeTarget) { item in
                    MergeSheet(item: item) { targetID in
                        Task { await viewModel.merge(item, targetNoteID: targetID) }
                    }
                }
        }
    }

    @ViewBuilder
    private var content: some View {
        if viewModel.isLoading && viewModel.isEmpty {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if viewModel.isEmpty {
            emptyState
        } else {
            List {
                ForEach(viewModel.items) { item in
                    ReviewItemCard(
                        item: item,
                        onApprove: { approve(item) },
                        onRedirect: { redirectTarget = item },
                        onMerge: { mergeTarget = item },
                        onDiscard: { discard(item) }
                    )
                    .listRowSeparator(.hidden)
                    .swipeActions(edge: .trailing) {
                        Button(role: .destructive) {
                            discard(item)
                        } label: {
                            Label("Discard", systemImage: "trash")
                        }
                    }
                    .swipeActions(edge: .leading) {
                        Button {
                            approve(item)
                        } label: {
                            Label("Approve", systemImage: "checkmark")
                        }
                        .tint(.green)
                    }
                }
            }
            .listStyle(.plain)
            .refreshable {
                await viewModel.load()
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "tray")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)

            Text("Inbox zero")
                .font(.title2.weight(.semibold))

            Text("Nothing waiting for review right now.")
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .combine)
    }

    private func approve(_ item: ReviewItemDTO) {
        haptic(.success)
        Task { await viewModel.approve(item) }
    }

    private func discard(_ item: ReviewItemDTO) {
        haptic(.warning)
        Task { await viewModel.discard(item) }
    }

    private func haptic(_ type: UINotificationFeedbackGenerator.FeedbackType) {
        UINotificationFeedbackGenerator().notificationOccurred(type)
    }
}

/// A single review item rendered as a card with the four primary actions.
private struct ReviewItemCard: View {
    let item: ReviewItemDTO
    let onApprove: () -> Void
    let onRedirect: () -> Void
    let onMerge: () -> Void
    let onDiscard: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let type = item.suggestedType {
                Text(type.capitalized)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
            }

            if let path = item.suggestedPath {
                Text(path)
                    .font(.headline)
            }

            if let reason = item.reason {
                Text(reason)
                    .font(.body)
                    .foregroundStyle(.secondary)
            }

            if let confidence = item.confidence {
                Text("Confidence: \(Int(confidence * 100))%")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }

            HStack(spacing: 12) {
                Button("Approve", action: onApprove)
                    .buttonStyle(.borderedProminent)
                    .tint(.green)

                Button("Redirect", action: onRedirect)
                    .buttonStyle(.bordered)

                Button("Merge", action: onMerge)
                    .buttonStyle(.bordered)

                Button("Discard", role: .destructive, action: onDiscard)
                    .buttonStyle(.bordered)
            }
            .font(.subheadline)
            .padding(.top, 4)
        }
        .padding(.vertical, 8)
        .accessibilityElement(children: .combine)
    }
}

/// Sheet for the redirect action — lets the user override the suggested type.
private struct RedirectSheet: View {
    let item: ReviewItemDTO
    let onSubmit: (RedirectPayload) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var type: String

    private static let types = ["fleeting", "permanent", "project", "reference", "journal"]

    init(item: ReviewItemDTO, onSubmit: @escaping (RedirectPayload) -> Void) {
        self.item = item
        self.onSubmit = onSubmit
        _type = State(initialValue: item.suggestedType ?? Self.types[0])
    }

    var body: some View {
        NavigationStack {
            Form {
                Picker("Type", selection: $type) {
                    ForEach(Self.types, id: \.self) { type in
                        Text(type.capitalized).tag(type)
                    }
                }
            }
            .navigationTitle("Redirect")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Apply") {
                        onSubmit(RedirectPayload(type: type, domain: nil, tags: nil, suggestedPath: nil))
                        dismiss()
                    }
                }
            }
        }
    }
}

/// Sheet for the merge action — collects the target note's UUID.
private struct MergeSheet: View {
    let item: ReviewItemDTO
    let onSubmit: (UUID) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var targetNoteIDText: String = ""

    private var targetID: UUID? {
        UUID(uuidString: targetNoteIDText.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Target note ID") {
                    TextField("UUID", text: $targetNoteIDText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                if !targetNoteIDText.isEmpty && targetID == nil {
                    Text("Enter a valid UUID.")
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
            .navigationTitle("Merge")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Merge") {
                        guard let targetID else { return }
                        onSubmit(targetID)
                        dismiss()
                    }
                    .disabled(targetID == nil)
                }
            }
        }
    }
}

#Preview {
    ReviewView(viewModel: ReviewViewModel(api: PreviewSporeAPI()))
}
