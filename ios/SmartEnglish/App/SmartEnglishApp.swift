import SwiftUI

@main
struct SmartEnglishApp: App {
    @State private var appState = AppState()
    @State private var language = LanguageManager()

    var body: some Scene {
        WindowGroup {
            HomeView()
                .environment(appState)
                .environment(language)
                // Instant RTL/LTR switch without restarting the app.
                .environment(\.layoutDirection, language.language.layoutDirection)
                .environment(\.locale, language.language.locale)
                .tint(Theme.Palette.primary)
        }
    }
}
