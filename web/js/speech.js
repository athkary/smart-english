// On-device speech via the browser's built-in Web Speech API (free, works on iPhone & Android).
// Phase 4 will add listening (speech recognition) for the voice classroom.

export function speechSupported() {
  return "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
}

function englishVoice() {
  const voices = window.speechSynthesis.getVoices();
  return voices.find((v) => v.lang === "en-US" && /samantha|google us english|aria|jenny/i.test(v.name))
      || voices.find((v) => v.lang === "en-US")
      || voices.find((v) => v.lang?.startsWith("en"));
}

export function speak(text, { slow = false } = {}) {
  const synth = window.speechSynthesis;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-US";
  const voice = englishVoice();
  if (voice) u.voice = voice;
  u.rate = slow ? 0.7 : 0.9;
  synth.speak(u);
  return u;
}

if (speechSupported()) window.speechSynthesis.getVoices(); // warm up the voice list (Chrome loads it async)
