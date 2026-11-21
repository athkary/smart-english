import SwiftUI

/// The mandatory bilingual vocabulary format (spec §3), as a reusable component.
struct VocabularyItem: Equatable, Sendable {
    let wordEn: String
    let meaningAr: String
    let phoneticAr: String
    let exampleEn: String
    let exampleAr: String

    static let apple = VocabularyItem(wordEn: "Apple", meaningAr: "تفاحة", phoneticAr: "أَبُل",
                                      exampleEn: "I eat an apple.", exampleAr: "أنا آكل تفاحة.")
}

struct VocabularyCard: View {
    let item: VocabularyItem
    let showArabic: Bool
    let speaker: DeviceSpeaker

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            HStack(alignment: .firstTextBaseline) {
                Text(item.wordEn.uppercased())
                    .font(Theme.Typography.word)
                    .foregroundStyle(Theme.Palette.primary)
                    .englishIsland()
                Spacer()
                ListenButton(label: item.wordEn) { speaker.speak(item.wordEn, slow: true) }
            }
            if showArabic {
                Text(item.meaningAr).font(Theme.Typography.title)
                    .frame(maxWidth: .infinity, alignment: .leading).arabicIsland()
                Text("النطق التقريبي: \(item.phoneticAr)")
                    .font(Theme.Typography.arabicBody)
                    .foregroundStyle(Theme.Palette.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading).arabicIsland()
            }
            Divider().padding(.vertical, Theme.Spacing.xs)
            HStack {
                Text(item.exampleEn).font(Theme.Typography.englishBody.weight(.semibold)).englishIsland()
                Spacer()
                ListenButton(label: item.exampleEn) { speaker.speak(item.exampleEn) }
            }
            if showArabic {
                Text(item.exampleAr).font(Theme.Typography.arabicBody)
                    .frame(maxWidth: .infinity, alignment: .leading).arabicIsland()
            }
        }
        .card()
    }
}

struct ListenButton: View {
    let label: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Image(systemName: "speaker.wave.2.fill")
                .font(.title3)
                .frame(width: 48, height: 48)                       // ≥44pt touch target for children
                .background(Theme.Palette.primary.opacity(0.12), in: Circle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(Theme.Palette.primary)
        .accessibilityLabel(Text("Listen: \(label)"))
    }
}
