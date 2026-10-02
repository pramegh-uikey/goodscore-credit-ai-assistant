async function loadDashboardScore() {
  const control = sectionExplanations['dashboard.credit_score'];
  try {
    const credit = await loadSectionData('/credit/summary');
    const score = sectionNumber(credit.score, 0, 1000);
    const change = sectionNumber(credit.change, -1000, 1000);
    const refreshedAt = new Date(credit.last_refreshed);
    if (!Number.isFinite(refreshedAt.getTime())) throw new Error('Invalid refresh date');
    const refreshed = `Last refreshed: ${Math.max(0, Math.floor((Date.now() - refreshedAt) / 3600000))} hours ago`;
    document.getElementById('score').textContent = score;
    const changeEl = document.getElementById('score-change');
    changeEl.textContent = `${change >= 0 ? '+' : ''}${change} points from last month`;
    changeEl.style.color = change >= 0 ? '#059669' : '#dc2626';
    document.getElementById('last-refreshed').textContent = refreshed;
    control.setSnapshot({score, change, refreshed});
  } catch (_) { control.fail(); }
}

async function loadDashboardTransactions() {
  const control = sectionExplanations['dashboard.top_transactions'];
  try {
    const data = await loadSectionData('/transactions/top');
    if (!Array.isArray(data)) throw new Error('Invalid transactions');
    const rows = data.map(row => {
      if (!['debit', 'credit'].includes(row.type)) throw new Error('Invalid transaction type');
      return {date: sectionDate(row.date), category: sectionString(row.category), type: row.type, amount: sectionNumber(row.amount)};
    });
    const table = document.getElementById('txnTable');
    table.replaceChildren();
    const header = document.createElement('tr');
    for (const label of ['Date', 'Category', 'Type', 'Amount']) header.append(sectionText('th', label));
    table.append(header);
    for (const row of rows) {
      const tr = document.createElement('tr');
      const color = row.type === 'debit' ? '#dc2626' : '#059669';
      for (const value of [row.date, row.category, row.type.toUpperCase(), `${row.type === 'debit' ? '-' : '+'}₹${row.amount.toLocaleString('en-IN')}`]) tr.append(sectionText('td', value));
      tr.children[2].style.color = color;
      tr.children[3].style.color = color;
      table.append(tr);
    }
    control.setSnapshot({rows}, rows.length > 0);
  } catch (_) { control.fail(); }
}

async function loadDashboardLoans() {
  const control = sectionExplanations['dashboard.active_loans'];
  try {
    const data = await loadSectionData('/loans/summary');
    if (!Array.isArray(data)) throw new Error('Invalid loans');
    const loans = data.filter(loan => loan.status === 'Active').map(loan => {
      const outstanding = sectionNumber(loan.outstanding);
      const original = sectionNumber(loan.original_amount, .01);
      if (outstanding > original) throw new Error('Invalid loan progress');
      return {
        id: sectionString(loan.id), name: sectionString(loan.name), type: sectionString(loan.type), outstanding,
        emi: sectionNumber(loan.emi), interest_rate: sectionNumber(loan.interest_rate, 0, 100),
        next_due_date: loan.next_due_date === null ? null : sectionDate(loan.next_due_date),
        tenure_remaining: sectionString(loan.tenure_remaining), percent_paid: Number(((original - outstanding) / original * 100).toFixed(1))
      };
    });
    const cards = document.getElementById('loanCards');
    cards.replaceChildren();
    for (const loan of loans) {
      const card = document.createElement('div');
      card.className = 'section-loan-card';
      card.append(sectionText('h3', loan.name), sectionText('p', loan.type));
      const dl = document.createElement('dl');
      for (const [label, value] of [['Outstanding', `₹${loan.outstanding.toLocaleString('en-IN')}`], ['EMI', `₹${loan.emi.toLocaleString('en-IN')}`],
          ['Interest Rate', `${loan.interest_rate}%`], ['Next Due', loan.next_due_date || 'Unavailable'], ['Tenure remaining', loan.tenure_remaining], ['Principal paid', `${loan.percent_paid}%`]]) {
        const field = document.createElement('div');
        field.append(sectionText('dt', label), sectionText('dd', value));
        dl.append(field);
      }
      card.append(dl);
      const progress = document.createElement('div');
      progress.className = 'section-progress';
      const fill = document.createElement('div');
      fill.style.width = loan.percent_paid + '%';
      progress.append(fill);
      const link = sectionText('a', 'View detailed breakdown →', 'link');
      link.href = 'loan-details.html#id=' + encodeURIComponent(loan.id);
      card.append(progress, link);
      cards.append(card);
    }
    control.setSnapshot({loans: loans.map(({id, ...shown}) => shown)}, loans.length > 0);
  } catch (_) { control.fail(); }
}

Promise.allSettled([loadDashboardScore(), loadDashboardTransactions(), loadDashboardLoans()]);
