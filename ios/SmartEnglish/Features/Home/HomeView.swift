import SwiftUI

/// Phase 1 home: connection status, bilingual sample, teachers, and an honest roadmap.
/// Every button here performs a real action (retry, settings, listen).
struct HomeView: View {
    @Environment(AppState.self) private var app
    @Environment(LanguageManager.self) private var lang
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var showSettings = false
    @State private var speaker = DeviceSpeaker()

    private var columns: [GridItem] {
        sizeClass == .regular
            ? [GridItem(.flexible(), spacing: Theme.Spacing.m), GridItem(.flexible(), spacing: Theme.Spacing.m)]
            : [GridItem(.flexible())]
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: Theme.Spacing.l) {
                    header
                    LazyVGrid(columns: columns, alignment: .leading, spacing: Theme.Spacing.m) {
                        ServerStatusCard()
                        VocabularyCard(item: .apple, showArabic: lang.showArabicTranslations, speaker: speaker)
                    }
                    if let meta = app.meta {
                        TeachersSection(teachers: meta.teachers, columns: columns)
                        RoadmapSection(features: meta.features)
                    }
                }
                .padding(Theme.Spacing.m)
                .frame(maxWidth: 1000)
                .frame(maxWidth: .infinity)
            }
            .background(Theme.Palette.background)
            .navigationTitle(lang.t("app.name"))
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape.fill") }
                        .accessibilityLabel(lang.t("settings.title"))
                }
            }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .refreshable { await app.refresh() }
        }
        .task { await app.refresh() }
    }

    private var header: some View {
        VStack(spacing: Theme.Spacing.s) {
            Text(lang.t("launch.welcome")).font(.largeTitle.bold())
            Text("Learn English. Speak with Confidence.")
                .font(Theme.Typography.englishBody.weight(.semibold))
                .foregroundStyle(Theme.Palette.primary)
                .englishIsland()
            if lang.showArabicTranslations {
                Text("تعلّم الإنجليزية. تحدّث بثقة.")
                    .font(Theme.Typography.arabicBody)
                    .foregroundStyle(Theme.Palette.textSecondary)
                    .arabicIsland()
            }
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
    }
}

struct ServerStatusCard: View {
    @Environment(AppState.self) private var app
    @Environment(LanguageManager.self) private var lang

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            Label(lang.t("launch.server.title"), systemImage: "antenna.radiowaves.left.and.right")
                .font(.headline)
            switch app.connection {
            case .checking:
                HStack { ProgressView(); Text(lang.t("launch.server.checking")) }
            case .connected(let meta):
                StatusPill(text: lang.t("launch.server.ok"), color: Theme.Palette.success)
                Text("\(lang.t("launch.server.version")): \(meta.serverVersion)")
                    .font(.footnote).foregroundStyle(Theme.Palette.textSecondary)
            case .updateRequired:
                StatusPill(text: lang.t("launch.server.update_required"), color: Theme.Palette.secondary)
            case .failed(let error):
                Text(error.message(arabic: lang.language == .arabic))
                    .foregroundStyle(Theme.Palette.danger)
                Button(lang.t("launch.server.retry")) { Task { await app.refresh() } }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
            }
        }
        .card()
    }
}

struct TeachersSection: View {
    @Environment(LanguageManager.self) private var lang
    let teachers: [TeacherInfo]
    let columns: [GridItem]

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            Text(lang.t("launch.teachers.title")).font(Theme.Typography.title)
            LazyVGrid(columns: columns, spacing: Theme.Spacing.m) {
                ForEach(teachers) { teacher in
                    HStack(spacing: Theme.Spacing.m) {
                        Circle()
                            .fill((Theme.Palette.teacherTints[teacher.code] ?? Theme.Palette.primary).gradient)
                            .frame(width: 56, height: 56)
                            .overlay(Text(String(teacher.displayName.prefix(1)))
                                .font(.title.bold()).foregroundStyle(.white))
                            .accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(teacher.displayName).font(.headline)
                            Text(lang.language == .arabic ? teacher.descriptionAr : teacher.descriptionEn)
                                .font(.subheadline).foregroundStyle(Theme.Palette.textSecondary)
                        }
                        Spacer()
                        if !teacher.available {
                            StatusPill(text: lang.t("launch.teachers.later"), color: Theme.Palette.textSecondary)
                        }
                    }
                    .card()
                }
            }
        }
    }
}

/// Shows exactly what the server reports as implemented — no dead buttons.
struct RoadmapSection: View {
    @Environment(LanguageManager.self) private var lang
    let features: FeatureFlags

    private struct Row: Identifiable { let key: String; let ready: Bool; var id: String { key } }

    private var rows: [Row] {
        [Row(key: "feature.parent_accounts", ready: features.parentAccounts),
         Row(key: "feature.ai_teacher", ready: features.aiTeacher),
         Row(key: "feature.voice_classroom", ready: features.voiceClassroom),
         Row(key: "feature.curriculum", ready: features.curriculum),
         Row(key: "feature.pronunciation", ready: features.pronunciationAssessment),
         Row(key: "feature.games", ready: features.games),
         Row(key: "feature.parent_dashboard", ready: features.parentDashboard)]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            Text(lang.t("launch.roadmap.title")).font(Theme.Typography.title)
            Text(lang.t("launch.roadmap.subtitle")).font(.footnote).foregroundStyle(Theme.Palette.textSecondary)
            VStack(spacing: 0) {
                ForEach(rows) { row in
                    HStack {
                        Text(lang.t(row.key))
                        Spacer()
                        StatusPill(text: lang.t(row.ready ? "feature.ready" : "feature.soon"),
                                   color: row.ready ? Theme.Palette.success : Theme.Palette.textSecondary)
                    }
                    .padding(.vertical, Theme.Spacing.s)
                    if row.key != rows.last?.key { Divider() }
                }
            }
            .card()
        }
    }
}
