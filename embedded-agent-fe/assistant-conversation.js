// Page-local only: no localStorage, cross-page state, or server conversation store.
class AssistantConversation {
  constructor(prefix, descriptionId, questionId) {
    this.prefix = prefix;
    this.history = [];
    this.enabled = false;
    this.busy = false;
    this.descriptionId = descriptionId;
    this.questionId = questionId;
    document.getElementById(questionId).style.boxSizing = 'border-box';
    this.ready = this.configure();
    document.getElementById(prefix + '-new-conversation').addEventListener('click', () => this.reset());
    // Browsers may restore in-memory documents from the back/forward cache.
    window.addEventListener('pageshow', event => { if (event.persisted) this.reset(); });
  }

  async configure() {
    try {
      const response = await fetch(API_BASE + '/assistant/config', {signal: AbortSignal.timeout(5000)});
      if (!response.ok) return;
      this.enabled = (await response.json()).insights_enabled === true;
      if (this.enabled) {
        document.getElementById(this.prefix + '-new-conversation').hidden = false;
        document.getElementById(this.descriptionId).textContent = this.prefix === 'txn'
          ? 'Ask about displayed rows, or get suggestions using your available transaction history.'
          : 'Ask about this loan, or get suggestions using its complete available payment history.';
        document.getElementById(this.questionId).placeholder = this.prefix === 'txn'
          ? 'e.g., How could I improve my spending habits based on my history?'
          : 'e.g., Based on this loan’s payment history, what could I improve?';
      }
    } catch (_) { /* Older backends keep the original widget behavior. */ }
  }

  setBusy(value) {
    this.busy = value;
    document.getElementById(this.prefix + '-new-conversation').disabled = value;
  }

  addTo(payload) {
    if (this.enabled && this.history.length) payload.history = this.history.map(item => ({...item}));
  }

  record(question, data) {
    if (!this.enabled || !data.mode) return;
    this.history.push({question, answer: data.answer});
    while (this.history.length > 10 || this.history.reduce((sum, item) => sum + item.question.length + item.answer.length, 0) > 30000) this.history.shift();
    const log = document.getElementById(this.prefix + '-conversation');
    log.replaceChildren();
    for (const [index, item] of this.history.entries()) {
      const turn = document.createElement('p');
      turn.textContent = 'You: ' + item.question + (index < this.history.length - 1 ? '\nAssistant: ' + item.answer : '');
      log.appendChild(turn);
    }
    const coverage = data.coverage || {};
    document.getElementById(this.prefix + '-coverage').textContent = coverage.scope === 'history'
      ? `Based on ${coverage.record_count} available records${coverage.from ? `, ${coverage.from} to ${coverage.to}` : ''}. Demo history.`
      : 'Based on displayed data.';
    log.hidden = false;
    log.scrollTop = log.scrollHeight;
  }

  clearCoverage() {
    document.getElementById(this.prefix + '-coverage').textContent = '';
  }

  reset() {
    if (this.busy) return;
    this.history = [];
    document.getElementById(this.prefix + '-conversation').replaceChildren();
    document.getElementById(this.questionId).value = '';
    this.clearCoverage();
    const responseId = this.prefix === 'txn' ? 'txn-ai-response' : 'ai-response';
    document.getElementById(responseId).style.display = 'none';
  }
}
