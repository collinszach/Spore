import UIKit
import SwiftUI
import UniformTypeIdentifiers

/// Share Sheet extension (Story 2.3 / FR2). Extracts shared text or a URL
/// from the host app's `NSExtensionItem` and enqueues a capture into the
/// shared App Group `CaptureStore` with source `"share_sheet"`. Images are
/// recorded as a placeholder reference for now.
final class ShareViewController: UIViewController {
    override func viewDidLoad() {
        super.viewDidLoad()

        let viewModel = ShareExtensionViewModel(extensionContext: extensionContext)
        let hosting = UIHostingController(rootView: ShareExtensionView(viewModel: viewModel))
        addChild(hosting)
        hosting.view.frame = view.bounds
        hosting.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(hosting.view)
        hosting.didMove(toParent: self)

        viewModel.loadAndCapture()
    }
}

/// Drives extraction + enqueue; isolated from `UIViewController` so it can
/// be reasoned about (and unit tested) independently.
@MainActor
final class ShareExtensionViewModel: ObservableObject {
    @Published var statusText: String = "Saving to Spore…"
    @Published var isDone: Bool = false

    private weak var extensionContext: NSExtensionContext?
    private let service: CaptureService

    init(extensionContext: NSExtensionContext?, service: CaptureService? = nil) {
        self.extensionContext = extensionContext
        self.service = service ?? .shared()
    }

    func loadAndCapture() {
        guard let item = extensionContext?.inputItems.first as? NSExtensionItem,
              let attachments = item.attachments, !attachments.isEmpty else {
            finish(status: "Nothing to save.")
            return
        }

        Task {
            let body = await Self.extractBody(from: attachments)
            if let body, !body.isEmpty {
                service.enqueue(body: body, source: "share_sheet")
                finish(status: "Saved to Spore.")
            } else {
                finish(status: "Nothing to save.")
            }
        }
    }

    private func finish(status: String) {
        statusText = status
        isDone = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [extensionContext] in
            extensionContext?.completeRequest(returningItems: nil)
        }
    }

    /// Extracts a plain-text body from the share attachments: prefers a
    /// shared URL, then plain text. Images are recorded as a placeholder
    /// reference (full image capture is a future story).
    static func extractBody(from attachments: [NSItemProvider]) async -> String? {
        for provider in attachments {
            if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                if let url = try? await loadItem(provider, type: UTType.url.identifier) as? URL {
                    return url.absoluteString
                }
            }
        }

        for provider in attachments {
            if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                if let text = try? await loadItem(provider, type: UTType.plainText.identifier) as? String {
                    return text
                }
            }
        }

        for provider in attachments {
            if provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
                return "[Shared image] \(provider.suggestedName ?? "untitled")"
            }
        }

        return nil
    }

    private static func loadItem(_ provider: NSItemProvider, type: String) async throws -> NSSecureCoding? {
        try await withCheckedThrowingContinuation { continuation in
            provider.loadItem(forTypeIdentifier: type, options: nil) { item, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: item)
                }
            }
        }
    }
}

/// Minimal share-sheet UI: shows a spinner/status, then dismisses itself.
struct ShareExtensionView: View {
    @ObservedObject var viewModel: ShareExtensionViewModel

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: viewModel.isDone ? "checkmark.circle.fill" : "arrow.up.circle")
                .font(.system(size: 40))
                .foregroundStyle(.tint)
            Text(viewModel.statusText)
                .font(.headline)
        }
        .padding(32)
    }
}
