import SwiftUI

/// Generic "coming soon" screen used for tabs that aren't built yet.
/// Real screens (Review/Pipeline/Notes/Today) will replace this body in
/// later stories while keeping the same tab scaffolding.
struct PlaceholderView: View {
    @State private var viewModel: PlaceholderViewModel

    init(viewModel: PlaceholderViewModel) {
        _viewModel = State(initialValue: viewModel)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                Image(systemName: viewModel.systemImage)
                    .font(.system(size: 48))
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)

                Text(viewModel.title)
                    .font(.title2.weight(.semibold))

                Text(viewModel.subtitle)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
            }
            .padding()
            .navigationTitle(viewModel.title)
            .accessibilityElement(children: .combine)
        }
    }
}

#Preview("Review") {
    PlaceholderView(viewModel: PlaceholderViewModel(
        title: "Review",
        subtitle: "Coming soon — swipe through triaged captures here.",
        systemImage: "checkmark.circle"
    ))
}

#Preview("Pipeline") {
    PlaceholderView(viewModel: PlaceholderViewModel(
        title: "Pipeline",
        subtitle: "Coming soon — see what's being processed.",
        systemImage: "arrow.triangle.2.circlepath"
    ))
}

#Preview("Notes") {
    PlaceholderView(viewModel: PlaceholderViewModel(
        title: "Notes",
        subtitle: "Coming soon — browse your Obsidian vault notes.",
        systemImage: "note.text"
    ))
}

#Preview("Today") {
    PlaceholderView(viewModel: PlaceholderViewModel(
        title: "Today",
        subtitle: "Coming soon — your daily digest and reminders.",
        systemImage: "sun.max"
    ))
}
