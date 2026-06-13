import SwiftUI

/// The Pipeline tab — read-only board of notes grouped by `idea_state` (Epic 7).
struct PipelineView: View {
    @State private var viewModel: PipelineViewModel

    init(viewModel: PipelineViewModel) {
        _viewModel = State(initialValue: viewModel)
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Pipeline")
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
                ForEach(viewModel.orderedStates, id: \.self) { state in
                    Section {
                        ForEach(viewModel.notes(for: state)) { note in
                            PipelineNoteRow(note: note)
                        }
                    } header: {
                        HStack {
                            Text(state.capitalized)
                            Spacer()
                            Text("\(viewModel.count(for: state))")
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .listStyle(.insetGrouped)
            .refreshable {
                await viewModel.load()
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "arrow.triangle.2.circlepath")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)

            Text("Nothing in the pipeline")
                .font(.title2.weight(.semibold))

            Text("Notes will appear here as captures are processed.")
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .combine)
    }
}

/// A single note row in the pipeline board.
private struct PipelineNoteRow: View {
    let note: PipelineNoteDTO

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(note.title ?? "Untitled")
                .font(.body)

            HStack(spacing: 8) {
                if let type = note.type {
                    Text(type.capitalized)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let domain = note.domain {
                    Text(domain)
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    PipelineView(viewModel: PipelineViewModel(api: PreviewSporeAPI()))
}
