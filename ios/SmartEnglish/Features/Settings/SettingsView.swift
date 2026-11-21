import SwiftUI

struct SettingsView: View {
    @Environment(LanguageManager.self) private var lang
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        @Bindable var lang = lang
        NavigationStack {
            Form {
                Section(lang.t("settings.language")) {
                    Picker(lang.t("settings.language"), selection: Binding(
                        get: { lang.language },
                        set: { lang.setLanguage($0) })) {
                        ForEach(AppLanguage.allCases) { Text($0.nativeName).tag($0) }
                    }
                    .pickerStyle(.segmented)
                }
                Section {
                    Toggle(lang.t("settings.show_arabic"), isOn: $lang.showArabicTranslations)
                } footer: {
                    Text(lang.t("settings.show_arabic.footer"))
                }
                Section(lang.t("settings.about")) {
                    LabeledContent(lang.t("settings.app_version"), value: app.environment.appVersion)
                }
            }
            .navigationTitle(lang.t("settings.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(lang.t("settings.done")) { dismiss() }
                }
            }
        }
        // Sheets don't inherit app-root overrides reliably; re-apply direction & locale.
        .environment(\.layoutDirection, lang.language.layoutDirection)
        .environment(\.locale, lang.language.locale)
    }
}
