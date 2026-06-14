import SwiftUI
import UIKit

/// Mic button for in-app voice capture (Story 2.6). Tap to start recording,
/// tap again to stop and upload. Offline-safe: failed uploads are retained
/// and retried on reconnect via `retryPending()`.
struct VoiceCaptureView: View {
    @State private var viewModel: VoiceCaptureViewModel
    private let networkMonitor: NetworkMonitor?

    init(viewModel: VoiceCaptureViewModel, networkMonitor: NetworkMonitor? = nil) {
        _viewModel = State(initialValue: viewModel)
        self.networkMonitor = networkMonitor
    }

    var body: some View {
        VStack(spacing: 8) {
            Button(action: toggleRecording) {
                Image(systemName: viewModel.isRecording ? "stop.circle.fill" : "mic.circle.fill")
                    .font(.system(size: 44))
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(viewModel.isRecording ? .red : .accentColor)
            }
            .accessibilityLabel(viewModel.isRecording ? "Stop recording" : "Record a voice capture")
            .accessibilityHint(viewModel.isRecording
                ? "Stops recording and uploads your voice capture"
                : "Starts recording a voice capture")

            if viewModel.isRecording {
                Text("Recording…")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else if !viewModel.pending.isEmpty {
                Text("\(viewModel.pending.count) voice capture(s) pending upload")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if let lastError = viewModel.lastError, !viewModel.pending.isEmpty {
                Text("Saved offline — will retry: \(lastError)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .onAppear {
            guard let networkMonitor else { return }
            let previous = networkMonitor.onReconnect
            networkMonitor.onReconnect = {
                previous?()
                Task { await viewModel.retryPending() }
            }
        }
    }

    private func toggleRecording() {
        if viewModel.isRecording {
            Task {
                await viewModel.stop()
                let generator = UINotificationFeedbackGenerator()
                generator.notificationOccurred(.success)
            }
        } else {
            Task {
                do {
                    try await viewModel.start()
                    let generator = UIImpactFeedbackGenerator(style: .medium)
                    generator.impactOccurred()
                } catch {
                    let generator = UINotificationFeedbackGenerator()
                    generator.notificationOccurred(.error)
                }
            }
        }
    }
}

#Preview {
    VoiceCaptureView(viewModel: VoiceCaptureViewModel(
        recorder: PreviewSupport.NoopRecorder(),
        api: PreviewSupport.NoopAudioAPI()
    ))
}
