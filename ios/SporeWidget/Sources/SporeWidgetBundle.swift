import WidgetKit
import SwiftUI

/// Entry point for the SporeWidget extension (Story 2.5 / FR4).
@main
struct SporeWidgetBundle: WidgetBundle {
    var body: some Widget {
        SporeCaptureWidget()
        if #available(iOS 18.0, *) {
            SporeCaptureControl()
        }
    }
}
