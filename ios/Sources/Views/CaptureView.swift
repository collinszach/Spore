import SwiftUI
import SwiftData
import UIKit

/// The Capture tab — the app's hero surface. Opens with keyboard focus so
/// the user can start typing immediately (NFR1: zero-friction capture).
struct CaptureView: View {
    @State private var viewModel: CaptureViewModel
    @State private var voiceViewModel: VoiceCaptureViewModel
    private let networkMonitor: NetworkMonitor?
    @FocusState private var isFocused: Bool

    init(viewModel: CaptureViewModel, voiceViewModel: VoiceCaptureViewModel, networkMonitor: NetworkMonitor? = nil) {
        _viewModel = State(initialValue: viewModel)
        _voiceViewModel = State(initialValue: voiceViewModel)
        self.networkMonitor = networkMonitor
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                Text("What's on your mind?")
                    .font(.headline)
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)

                TextEditor(text: $viewModel.draft)
                    .focused($isFocused)
                    .frame(minHeight: 160)
                    .padding(8)
                    .background(.background.secondary, in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityLabel("Capture text")
                    .accessibilityHint("Enter a thought to save it to Spore")

                Button(action: submit) {
                    Label("Capture", systemImage: "arrow.up.circle.fill")
                        .font(.title3.weight(.semibold))
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!viewModel.canSubmit)
                .accessibilityHint("Saves your thought and clears the field")

                HStack {
                    Spacer()
                    VoiceCaptureView(viewModel: voiceViewModel, networkMonitor: networkMonitor)
                    Spacer()
                }
                .padding(.top, 8)

                Spacer()
            }
            .padding()
            .navigationTitle("Capture")
            .onAppear {
                isFocused = true
                viewModel.drainQueue()
            }
        }
    }

    private func submit() {
        guard viewModel.submit() != nil else { return }
        let generator = UINotificationFeedbackGenerator()
        generator.notificationOccurred(.success)
        isFocused = true
    }
}

#Preview {
    let container = PreviewSupport.container
    let store = SwiftDataCaptureStore(modelContext: container.mainContext)
    CaptureView(
        viewModel: CaptureViewModel(
            queue: CaptureQueue(
                store: store,
                api: PreviewSupport.NoopAPI()
            )
        ),
        voiceViewModel: VoiceCaptureViewModel(
            recorder: PreviewSupport.NoopRecorder(),
            api: PreviewSupport.NoopAudioAPI()
        )
    )
    .modelContainer(container)
}
