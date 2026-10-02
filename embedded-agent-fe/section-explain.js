/* Explanations stay with their rendered section; no chat or history retrieval. */
function sectionSpeechSupported() {
  return Boolean(window.speechSynthesis && typeof window.speechSynthesis.speak === 'function' &&
    typeof window.speechSynthesis.cancel === 'function' && typeof window.SpeechSynthesisUtterance === 'function');
}
const SectionSpeech = {
  owner: null,
  generation: 0,
  stop() {
    this.generation++;
    if (window.speechSynthesis && typeof window.speechSynthesis.cancel === 'function') {
      try { window.speechSynthesis.cancel(); } catch (_) { /* Text remains available if the voice service stops. */ }
    }
    if (this.owner) this.owner.audioState(false);
    this.owner = null;
  },
  speak(owner, text) {
    this.stop();
    if (!sectionSpeechSupported()) {
      owner.audioStatus.textContent = 'Read aloud is unavailable in this browser. You can still read the explanation.';
      return;
    }
    this.owner = owner;
    const generation = this.generation;
    let voices = [];
    try { voices = window.speechSynthesis.getVoices(); } catch (_) { /* Let the engine choose its default voice. */ }
    const voice = voices.find(v => /^en[-_]IN$/i.test(v.lang)) || voices.find(v => /^en\b/i.test(v.lang));
    // Small utterances avoid long-reading cutoffs in browser speech engines.
    const chunks = text.match(/.{1,260}(?:\s|$)|\S+/g) || [text];
    owner.audioState(true);
    owner.audioStatus.textContent = 'Reading aloud…';
    const next = () => {
      if (this.owner !== owner || generation !== this.generation) return;
      if (!chunks.length) {
        owner.audioState(false);
        owner.audioStatus.textContent = 'Finished reading.';
        this.owner = null;
        return;
      }
      const utterance = new SpeechSynthesisUtterance(chunks.shift().trim());
      utterance.lang = voice ? voice.lang : 'en-IN';
      if (voice) utterance.voice = voice;
      utterance.onend = next;
      utterance.onerror = () => {
        if (this.owner !== owner || generation !== this.generation) return;
        this.stop();
        owner.audioStatus.textContent = 'Audio could not play. Try Read aloud again, or read the text.';
      };
      owner.utterance = utterance;
      try { window.speechSynthesis.speak(utterance); }
      catch (_) { utterance.onerror(); }
    };
    next();
  }
};
window.addEventListener('pagehide', () => SectionSpeech.stop());

class SectionExplanation {
  constructor(button) {
    this.button = button;
    this.section = button.dataset.explain;
    this.container = button.closest('.section');
    this.snapshot = null;
    this.cache = null;
    this.version = 0;
    this.controller = null;
    this.open = false;
    this.button.disabled = true;
    this.button.textContent = 'Explain';
    this.button.setAttribute('aria-expanded', 'false');
    this.status = document.createElement('p');
    this.status.className = 'section-data-status';
    this.status.setAttribute('role', 'status');
    this.status.textContent = 'Loading section…';
    this.panel = document.createElement('div');
    this.panel.id = 'explain-' + this.section.replaceAll('.', '-');
    this.panel.className = 'explain-panel';
    this.panel.hidden = true;
    this.panel.setAttribute('role', 'region');
    this.panel.setAttribute('aria-live', 'polite');
    this.panel.setAttribute('aria-label', this.container.querySelector('h2').textContent + ' explanation');
    this.button.setAttribute('aria-controls', this.panel.id);
    // Keep the explanation beside its trigger, before the section's data.
    // The native hidden state removes it from normal flow when collapsed.
    this.container.querySelector('.header').after(this.panel, this.status);
    this.button.addEventListener('click', () => this.open ? this.close() : this.show());
    window.addEventListener('pagehide', () => this.close());
  }

  setSnapshot(snapshot, hasData = true) {
    const copy = JSON.parse(JSON.stringify(snapshot));
    const key = JSON.stringify(copy);
    if (key !== this.key) {
      this.close();
      this.cache = null;
      this.key = key;
    }
    this.snapshot = copy;
    this.button.disabled = !hasData;
    this.status.textContent = hasData ? '' : 'No data in this section to explain yet.';
  }

  fail(message = 'This section could not load. Reload the page to try again.') {
    this.close();
    this.snapshot = null;
    this.cache = null;
    this.button.disabled = true;
    this.status.textContent = message;
  }

  close() {
    this.version++;
    if (this.controller) this.controller.abort();
    this.controller = null;
    if (SectionSpeech.owner === this) SectionSpeech.stop();
    this.open = false;
    this.panel.hidden = true;
    this.button.textContent = 'Explain';
    this.button.setAttribute('aria-expanded', 'false');
    this.panel.removeAttribute('aria-busy');
  }

  async show() {
    if (!this.snapshot || this.button.disabled) return;
    this.open = true;
    this.button.textContent = 'Hide explanation';
    this.button.setAttribute('aria-expanded', 'true');
    this.panel.hidden = false;
    if (this.cache) { this.render(this.cache); return; }
    const version = ++this.version;
    const controller = new AbortController();
    this.controller = controller;
    const timer = setTimeout(() => controller.abort(), 45000);
    this.panel.setAttribute('aria-busy', 'true');
    this.panel.replaceChildren();
    const loading = document.createElement('p');
    loading.setAttribute('role', 'status');
    loading.textContent = 'Explaining this section…';
    this.panel.append(loading);
    try {
      const response = await fetch(API_BASE + '/sections/explain', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, signal: controller.signal,
        body: JSON.stringify({section: this.section, snapshot: this.snapshot})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'The explanation could not be generated.');
      if (result.section !== this.section || typeof result.meaning !== 'string' || !result.meaning.trim() ||
          !Array.isArray(result.key_points) || !result.key_points.length || !Array.isArray(result.takeaways) || !result.takeaways.length ||
          [...result.key_points, ...result.takeaways].some(item => typeof item !== 'string' || !item.trim())) throw new Error('The explanation returned an invalid response.');
      if (!this.open || version !== this.version) return;
      this.cache = result;
      this.render(result);
    } catch (error) {
      if (!this.open || version !== this.version) return;
      this.panel.replaceChildren();
      const message = document.createElement('p');
      message.setAttribute('role', 'alert');
      message.textContent = error.name === 'AbortError' ? 'The explanation took too long. Please try again.' : error.message;
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.textContent = 'Retry explanation';
      retry.addEventListener('click', () => this.show());
      this.panel.append(message, retry);
    } finally {
      clearTimeout(timer);
      if (version === this.version) {
        this.controller = null;
        this.panel.removeAttribute('aria-busy');
      }
    }
  }

  render(result) {
    this.panel.replaceChildren();
    for (const [title, content] of [['What this means', result.meaning], ['Your information', result.key_points], ['Points to notice', result.takeaways]]) {
      const heading = document.createElement('h3');
      heading.textContent = title;
      const body = document.createElement(Array.isArray(content) ? 'ul' : 'p');
      if (Array.isArray(content)) {
        for (const item of content) { const li = document.createElement('li'); li.textContent = item; body.append(li); }
      } else body.textContent = content;
      this.panel.append(heading, body);
    }
    // Explicit separators preserve the same headings and words when spoken.
    this.speechText = `What this means. ${result.meaning} Your information. ${result.key_points.join(' ')} Points to notice. ${result.takeaways.join(' ')}`;
    const controls = document.createElement('div');
    controls.className = 'explain-audio-controls';
    this.readButton = document.createElement('button');
    this.readButton.type = 'button';
    this.readButton.textContent = 'Read aloud';
    this.stopButton = document.createElement('button');
    this.stopButton.type = 'button';
    this.stopButton.textContent = 'Stop';
    this.stopButton.disabled = true;
    this.audioStatus = document.createElement('span');
    this.audioStatus.setAttribute('role', 'status');
    this.readButton.addEventListener('click', () => SectionSpeech.speak(this, this.speechText));
    this.stopButton.addEventListener('click', () => { SectionSpeech.stop(); this.audioStatus.textContent = 'Stopped.'; });
    if (!sectionSpeechSupported()) {
      this.readButton.disabled = true;
      this.audioStatus.textContent = 'Read aloud is unavailable in this browser.';
    }
    controls.append(this.readButton, this.stopButton, this.audioStatus);
    this.panel.append(controls);
  }

  audioState(playing) {
    this.readButton.disabled = playing;
    this.stopButton.disabled = !playing;
    if (!playing) this.audioStatus.textContent = '';
  }
}

const sectionExplanations = Object.fromEntries([...document.querySelectorAll('[data-explain]')].map(button => [button.dataset.explain, new SectionExplanation(button)]));
const pickSectionFields = (source, fields) => Object.fromEntries(fields.map(key => [key, source[key]]));
const sectionText = (tag, text, className) => {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
};
async function loadSectionData(path) {
  const response = await fetch(API_BASE + path, {signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw new Error('Section data unavailable');
  return response.json();
}
function sectionNumber(value, minimum = 0, maximum = 1e12) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) throw new Error('Invalid section number');
  return value;
}
function sectionString(value) {
  if (typeof value !== 'string' || !value.trim() || value.length > 500) throw new Error('Invalid section text');
  return value;
}
function sectionDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error('Invalid section date');
  return value;
}
