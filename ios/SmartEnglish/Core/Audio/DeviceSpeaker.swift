import AVFoundation

/// On-device English speech (AVSpeechSynthesizer). Real audio, works offline.
/// Used in Phase 1 for the sample word card only. Lessons will use reviewed
/// natural audio served by the backend (Phase 5) and the live teacher voice (Phase 4).
@MainActor
final class DeviceSpeaker {
    private let synthesizer = AVSpeechSynthesizer()

    func speak(_ text: String, slow: Bool = false) {
        if synthesizer.isSpeaking { synthesizer.stopSpeaking(at: .immediate) }
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? session.setActive(true)
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate = slow ? AVSpeechUtteranceDefaultSpeechRate * 0.7 : AVSpeechUtteranceDefaultSpeechRate * 0.9
        synthesizer.speak(utterance)
    }
}
