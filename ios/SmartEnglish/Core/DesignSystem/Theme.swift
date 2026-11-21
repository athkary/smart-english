import SwiftUI

/// Design tokens. Colorful but calm, high contrast for young readers, Arabic-friendly type.
enum Theme {
    enum Palette {
        static let primary = Color(red: 0.20, green: 0.42, blue: 0.95)     // friendly blue
        static let secondary = Color(red: 0.99, green: 0.62, blue: 0.20)   // warm orange (rewards)
        static let success = Color(red: 0.16, green: 0.68, blue: 0.42)
        static let danger = Color(red: 0.90, green: 0.27, blue: 0.30)
        static let background = Color(uiColor: .systemGroupedBackground)
        static let card = Color(uiColor: .secondarySystemGroupedBackground)
        static let textSecondary = Color(uiColor: .secondaryLabel)
        static let teacherTints: [String: Color] = [
            "emma": Color(red: 0.93, green: 0.38, blue: 0.60),
            "daniel": Color(red: 0.20, green: 0.55, blue: 0.85),
            "alex": Color(red: 0.45, green: 0.35, blue: 0.85),
        ]
    }

    enum Spacing {
        static let xs: CGFloat = 4, s: CGFloat = 8, m: CGFloat = 16, l: CGFloat = 24, xl: CGFloat = 32
    }

    enum Radius { static let card: CGFloat = 20, chip: CGFloat = 12 }

    enum Typography {
        /// Large English display text (vocabulary word).
        static let word = Font.system(size: 40, weight: .heavy, design: .rounded)
        /// Arabic body text is set slightly larger than English for legibility.
        static let arabicBody = Font.system(size: 19, weight: .regular)
        static let englishBody = Font.system(.body, design: .rounded)
        static let title = Font.system(.title2, design: .rounded).weight(.bold)
    }
}

struct CardStyle: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(Theme.Spacing.m)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.Palette.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
            .shadow(color: .black.opacity(0.06), radius: 8, y: 3)
    }
}

extension View {
    func card() -> some View { modifier(CardStyle()) }

    /// Forces a left-to-right island (e.g. English sentence) inside an RTL screen.
    func englishIsland() -> some View { environment(\.layoutDirection, .leftToRight) }
    func arabicIsland() -> some View { environment(\.layoutDirection, .rightToLeft) }
}

struct StatusPill: View {
    let text: String
    let color: Color
    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10).padding(.vertical, 4)
            .background(color.opacity(0.15), in: Capsule())
            .foregroundStyle(color)
    }
}
