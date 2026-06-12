---
name: swiftui-screen
description: Conventions for adding a SwiftUI screen to Spore — MVVM, navigation, SwiftData
  access, accessibility, and the standard preview + XCTest scaffold. Use when building any ios/ screen.
---
- MVVM: View + @Observable ViewModel; no business logic in views.
- Data via the shared SwiftData container; capture writes go through CaptureQueue (offline-safe).
- Every screen ships a #Preview and a ViewModel unit test.
- Respect Dynamic Type + VoiceOver labels. Haptics on review swipes.
