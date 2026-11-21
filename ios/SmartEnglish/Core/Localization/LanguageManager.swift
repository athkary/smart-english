import SwiftUI

enum AppLanguage: String, CaseIterable, Identifiable, Sendable {
    case arabic = "ar"
    case english = "en"

    var id: String { rawValue }
    var layoutDirection: LayoutDirection { self == .arabic ? .rightToLeft : .leftToRight }
    var locale: Locale { Locale(identifier: rawValue) }
    /// Native name, shown identically in both UI languages.
    var nativeName: String { self == .arabic ? "العربية" : "English" }
}

/// Owns UI language (instant switch, no restart) and the "show Arabic translations" setting.
@MainActor
@Observable
final class LanguageManager {
    private(set) var language: AppLanguage
    var showArabicTranslations: Bool {
        didSet { defaults.set(showArabicTranslations, forKey: Keys.showArabic) }
    }

    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let bundle: Bundle
    @ObservationIgnored private var tableCache: [AppLanguage: [String: String]] = [:]

    private enum Keys {
        static let language = "ui.language"
        static let showArabic = "ui.showArabicTranslations"
    }

    init(defaults: UserDefaults = .standard, bundle: Bundle = .main) {
        self.defaults = defaults
        self.bundle = bundle
        // Default to Arabic: the initial audience is Arabic-speaking beginners.
        self.language = defaults.string(forKey: Keys.language).flatMap(AppLanguage.init(rawValue:)) ?? .arabic
        self.showArabicTranslations = defaults.object(forKey: Keys.showArabic) as? Bool ?? true
    }

    func setLanguage(_ newValue: AppLanguage) {
        language = newValue
        defaults.set(newValue.rawValue, forKey: Keys.language)
    }

    var isRTL: Bool { language.layoutDirection == .rightToLeft }

    /// Localized UI string for the current language; falls back to English, then to the key.
    func t(_ key: String) -> String {
        if let value = table(for: language)[key] { return value }
        if let value = table(for: .english)[key] { return value }
        return key
    }

    private func table(for lang: AppLanguage) -> [String: String] {
        if let cached = tableCache[lang] { return cached }
        guard let path = bundle.path(forResource: "Localizable", ofType: "strings", inDirectory: nil,
                                     forLocalization: lang.rawValue),
              let dict = NSDictionary(contentsOfFile: path) as? [String: String] else { return [:] }
        tableCache[lang] = dict
        return dict
    }
}
