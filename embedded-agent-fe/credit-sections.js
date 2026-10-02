async function loadCurrentScore() {
  const control = sectionExplanations['credit.current_score'];
  try {
    const credit = await loadSectionData('/credit/summary');
    const score = sectionNumber(credit.score, 0, 1000);
    const previous_score = sectionNumber(credit.previous_score, 0, 1000);
    const change = sectionNumber(credit.change, -1000, 1000);
    if (score - previous_score !== change) throw new Error('Inconsistent score change');
    const date = new Date(credit.last_refreshed);
    if (!Number.isFinite(date.getTime())) throw new Error('Invalid refresh date');
    const refreshed = `Last refreshed: ${Math.max(0, Math.floor((Date.now() - date) / 3600000))} hours ago (${date.toLocaleString()})`;
    document.getElementById('current-score').textContent = score;
    const changeEl = document.getElementById('score-change');
    changeEl.textContent = `${change >= 0 ? '↑ +' : '↓ '}${change} points from last month (${previous_score})`;
    changeEl.style.color = change >= 0 ? '#059669' : '#dc2626';
    document.getElementById('score-indicator').style.left = Math.max(0, Math.min(100, (score - 300) / 550 * 100)) + '%';
    document.getElementById('last-refreshed').textContent = refreshed;
    control.setSnapshot({score, previous_score, change, range_min: 300, range_max: 850, refreshed});
  } catch (_) { control.fail(); }
}

async function loadScoreTrend() {
  const control = sectionExplanations['credit.score_trend'];
  try {
    const data = await loadSectionData('/credit/history');
    if (!Array.isArray(data.history)) throw new Error('Invalid score history');
    const history = data.history.map(row => ({date: sectionDate(row.date), score: sectionNumber(row.score, 0, 1000)}));
    if (history.some((row, index) => index > 0 && row.date < history[index - 1].date)) throw new Error('Unordered chart');
    drawScoreTrend(history);
    control.setSnapshot({history}, history.length > 0);
  } catch (_) { control.fail(); }
}

async function loadScoreDetails() {
  let details;
  try { details = await loadSectionData('/credit/details'); }
  catch (_) { sectionExplanations['credit.factors'].fail(); sectionExplanations['credit.breakdown'].fail(); return; }
  try {
    if (!Array.isArray(details.reasons)) throw new Error('Invalid reasons');
    const reasons = details.reasons.map(sectionString);
    const list = document.getElementById('reasons');
    list.replaceChildren(...reasons.map(reason => sectionText('li', reason)));
    sectionExplanations['credit.factors'].setSnapshot({reasons}, reasons.length > 0);
  } catch (_) { sectionExplanations['credit.factors'].fail(); }
  try {
    if (!Array.isArray(details.breakdown)) throw new Error('Invalid breakdown');
    const breakdown = details.breakdown.map(item => ({label: sectionString(item.label), percent: sectionNumber(item.percent, 0, 100)}));
    const root = document.getElementById('score-breakdown');
    root.replaceChildren();
    for (const item of breakdown) {
      const block = document.createElement('div');
      block.style.marginBottom = '18px';
      const labels = document.createElement('div');
      labels.style.cssText = 'display:flex;justify-content:space-between;margin-bottom:8px';
      labels.append(sectionText('span', item.label), sectionText('strong', item.percent + '%'));
      const bar = document.createElement('div');
      bar.className = 'section-progress';
      const fill = document.createElement('div');
      fill.style.width = item.percent + '%';
      bar.append(fill);
      block.append(labels, bar);
      root.append(block);
    }
    sectionExplanations['credit.breakdown'].setSnapshot({breakdown}, breakdown.length > 0);
  } catch (_) { sectionExplanations['credit.breakdown'].fail(); }
}

function drawScoreTrend(history) {
  const canvas = document.getElementById('score-chart');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', history.length ? 'Score history: ' + history.map(row => `${row.date}: ${row.score}`).join('; ') : 'No score history available');
  if (!history.length) return;
  const pad = {left: 45, right: 35, top: 20, bottom: 40};
  const width = canvas.width - pad.left - pad.right;
  const height = canvas.height - pad.top - pad.bottom;
  const scores = history.map(row => row.score);
  const minimum = Math.min(...scores) - 10;
  const maximum = Math.max(...scores) + 10;
  const x = index => pad.left + width * index / Math.max(1, history.length - 1);
  const y = score => pad.top + height - (score - minimum) / (maximum - minimum) * height;
  ctx.font = '12px Arial';
  ctx.strokeStyle = '#e5e7eb';
  ctx.fillStyle = '#6b7280';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const gridY = pad.top + height * i / 4;
    ctx.beginPath(); ctx.moveTo(pad.left, gridY); ctx.lineTo(pad.left + width, gridY); ctx.stroke();
    ctx.fillText(String(Math.round(maximum - (maximum - minimum) * i / 4)), 6, gridY + 4);
  }
  history.forEach((row, index) => {
    if (index % 2 === 0 || index === history.length - 1) ctx.fillText(new Date(row.date + 'T00:00:00').toLocaleString('en-US', {month: 'short', year: '2-digit'}), x(index) - 12, pad.top + height + 24);
  });
  ctx.strokeStyle = '#3b82f6'; ctx.lineWidth = 2; ctx.beginPath();
  history.forEach((row, index) => index ? ctx.lineTo(x(index), y(row.score)) : ctx.moveTo(x(index), y(row.score)));
  ctx.stroke();
  history.forEach((row, index) => {
    ctx.fillStyle = index === history.length - 1 ? '#059669' : '#2563eb';
    ctx.beginPath(); ctx.arc(x(index), y(row.score), index === history.length - 1 ? 5 : 3, 0, Math.PI * 2); ctx.fill();
  });
}

Promise.allSettled([loadCurrentScore(), loadScoreTrend(), loadScoreDetails()]);
