// Browser feedback complements the server's durable ntfy delivery.
const tones = {
  boop: [440],
  bell: [784, 1175],
  ding: [1047],
  alert: [740, 554, 740],
  chime: [523, 659, 784],
};
let audio;
export function unlock() {
  try {
    audio ??= new AudioContext();
    audio.resume().catch(() => {});
  } catch {}
}
export function play(sound) {
  if (!tones[sound] || audio?.state !== "running") return;
  tones[sound].forEach((hz, i) => {
    const t = audio.currentTime + i * 0.14,
      o = audio.createOscillator(),
      gain = audio.createGain();
    o.type = sound === "alert" ? "triangle" : "sine";
    o.frequency.value = hz;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.12, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.32);
    o.connect(gain);
    gain.connect(audio.destination);
    o.start(t);
    o.stop(t + 0.34);
  });
}
export function browserFeedback(pref, events, previous) {
  if (previous === null) return;
  for (const e of events.filter((x) => x.id > previous).reverse()) {
    play(e.sound);
    if (pref && window.Notification?.permission === "granted") {
      try {
        new Notification(e.ruleName, {
          body: e.message,
          tag: `screenit-${e.id}`,
        });
      } catch {}
    }
  }
}
