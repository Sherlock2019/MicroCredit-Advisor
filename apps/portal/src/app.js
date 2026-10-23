/* MicroCredit Advisor portal: plain JavaScript, no build step. Every action calls the platform API. */
(() => {
  const $app = document.getElementById('app');
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  const state = { token: null, me: null, users: [] };
  const fmtMoney = (v, ccy = '') => (v === null || v === undefined || v === '') ? '—'
    : `${Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })}${ccy ? ' ' + ccy : ''}`;
  const fmtNum = (v) => (v === null || v === undefined) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 });
  const pill = (text, cls = text) => `<span class="pill ${esc(cls)}">${esc(String(text).replaceAll('_', ' '))}</span>`;
  const can = (perm) => !!state.me && state.me.permissions.includes(perm);

  async function api(path, { method = 'GET', body, form } = {}) {
    const headers = { Accept: 'application/json' };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (path.startsWith('/dev/') && store.get('demoKey')) headers['X-Demo-Key'] = store.get('demoKey');
    let payload;
    if (form) payload = form; else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
    const res = await fetch(`/api/v1${path}`, { method, headers, body: payload });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data?.error?.message || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }
  const errBox = (e) => `<div class="err">${esc(e.message)}${e.status === 403 ? ' — switch to an account with the right role (top right).' : ''}</div>`;

  // ------------------------------------------------------------------------------------------------ identity
  async function login(username) {
    const t = await api('/dev/token', { method: 'POST', body: { username } });
    state.token = t.access_token;
    store.set('demoUser', username);
    state.me = await api('/me');
  }
  async function initUsers() {
    const sel = document.getElementById('userSelect');
    for (let attempt = 0; ; attempt += 1) {
      try {
        state.users = (await api('/dev/users')).users;
        break;
      } catch (e) {
        if (e.status === 401 && attempt < 3) {
          const key = window.prompt('This demo is protected. Enter the demo access key printed by start.sh:');
          if (key) { store.set('demoKey', key.trim()); continue; }
        }
        sel.outerHTML = '<span class="small">Sign-in not available</span>';
        return;
      }
    }
    sel.innerHTML = state.users.map((u) => `<option value="${esc(u.username)}">${esc(u.name)}</option>`).join('');
    const initial = store.get('demoUser') || 'fatima.finance';
    sel.value = state.users.some((u) => u.username === initial) ? initial : state.users[0].username;
    await login(sel.value);
    sel.addEventListener('change', async () => { await login(sel.value); route(); });
  }

  // ------------------------------------------------------------------------------------------------ charts
  function cashChart(months, ccy) {
    const W = 760, H = 250, P = { l: 64, r: 10, t: 12, b: 34 };
    const inflow = months.map((m) => +m.harvest_revenue + +m.other_income + +m.loan_disbursement);
    const outflow = months.map((m) => +m.production_costs + +m.investment_costs + +m.operating_expenses + +m.existing_obligations + +m.debt_service);
    const bal = months.map((m) => +m.closing_balance);
    const max = Math.max(...inflow, ...bal, 1), min = Math.min(-Math.max(...outflow, 1), ...bal, 0);
    const y = (v) => P.t + (max - v) / (max - min) * (H - P.t - P.b);
    const bw = (W - P.l - P.r) / months.length;
    const x = (i) => P.l + i * bw;
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Monthly cash flow">`;
    [max, (max + min) / 2, min, 0].forEach((v) => { s += `<line x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}" stroke="${v === 0 ? '#9aa59f' : '#eceeed'}"/><text x="${P.l - 6}" y="${y(v) + 4}" text-anchor="end">${esc(fmtMoney(Math.round(v)))}</text>`; });
    months.forEach((m, i) => {
      s += `<rect x="${x(i) + bw * .15}" y="${y(inflow[i])}" width="${bw * .32}" height="${Math.max(0, y(0) - y(inflow[i]))}" fill="var(--in)"><title>${esc(m.label)} inflow ${esc(fmtMoney(inflow[i], ccy))}</title></rect>`;
      s += `<rect x="${x(i) + bw * .5}" y="${y(0)}" width="${bw * .32}" height="${Math.max(0, y(-outflow[i]) - y(0))}" fill="var(--out)"><title>${esc(m.label)} outflow ${esc(fmtMoney(outflow[i], ccy))}</title></rect>`;
      s += `<text x="${x(i) + bw / 2}" y="${H - 14}" text-anchor="middle">${esc(m.label.slice(2))}</text>`;
    });
    s += `<polyline fill="none" stroke="var(--bal)" stroke-width="2.5" points="${bal.map((v, i) => `${x(i) + bw / 2},${y(v)}`).join(' ')}"/>`;
    bal.forEach((v, i) => { s += `<circle cx="${x(i) + bw / 2}" cy="${y(v)}" r="3.5" fill="${v < 0 ? 'var(--high)' : 'var(--bal)'}"><title>${esc(months[i].label)} closing balance ${esc(fmtMoney(v, ccy))}</title></circle>`; });
    return s + '</svg><div class="legend"><span><i style="background:var(--in)"></i>Inflows</span><span><i style="background:var(--out)"></i>Outflows incl. debt service</span><span><i style="background:var(--bal)"></i>Month-end balance (red = negative)</span></div>';
  }

  function barChart(rows, ccy) { // [{label, value}] horizontal bars
    const max = Math.max(...rows.map((r) => +r.value), 1);
    return rows.map((r) => `<div class="small">${esc(r.label)} — ${esc(fmtMoney(r.value, ccy))}<div style="background:var(--brand-soft);border-radius:4px"><div style="width:${Math.max(1, (+r.value / max) * 100)}%;height:10px;background:var(--brand);border-radius:4px"></div></div></div>`).join('');
  }

  // ------------------------------------------------------------------------------------------------ home
  async function home() {
    let caps;
    try { caps = await api('/platform/capabilities'); } catch (e) { $app.innerHTML = errBox(e); return; }
    $app.innerHTML = `
      <h1>One platform, two copilots</h1>
      <div class="grid">
        ${caps.applications.map((a) => `<div class="card"><h2>${esc(a.name)}</h2><p class="small">${a.capabilities.map(esc).join(' · ')}</p>
          <a class="btn" href="${a.id === 'rural-finance' ? '#/finance' : '#/projects'}">Open</a></div>`).join('')}
        <div class="card"><h2>Farmer mobile app</h2><p class="small">Design mockup of the borrower app for sending crop photos and scanned documents. Not connected to the API.</p>
          <a class="btn" href="farmer-mockup.html" target="_blank" rel="noopener">View mockup</a></div>
      </div>
      <div class="card"><h2>Shared platform</h2>
        <div class="tiles">
          <div class="tile"><div class="v">${esc(caps.version)}</div><div class="l">version · ${esc(caps.commit_sha.slice(0, 7))}</div></div>
          <div class="tile"><div class="v">${esc(caps.deployment_target)}</div><div class="l">deployment</div></div>
          <div class="tile"><div class="v">${esc(caps.model_provider)}</div><div class="l">model provider</div></div>
          <div class="tile"><div class="v">${esc(caps.embedding_provider)}</div><div class="l">embeddings</div></div>
        </div>
        <p class="small">${caps.shared_services.map(esc).join(' · ')}</p>
        <p class="small muted">Signed in as <strong>${esc(state.me?.subject)}</strong> (${esc((state.me?.roles || []).join(', '))}) · tenant ${esc(state.me?.tenant_id)}</p>
      </div>`;
  }

  // ------------------------------------------------------------------------------------------------ finance
  async function financeList() {
    let data;
    try { data = await api('/finance/applications?limit=100'); } catch (e) { $app.innerHTML = `<h1>Loan officer workspace</h1>${errBox(e)}`; return; }
    const by = {};
    data.items.forEach((a) => { by[a.status] = (by[a.status] || 0) + 1; });
    $app.innerHTML = `<h1>Loan officer workspace</h1>
      <div class="tiles">${['SUBMITTED', 'ANALYZED', 'IN_REVIEW', 'NEEDS_INFORMATION', 'APPROVED'].map((s) => `<div class="tile"><div class="v">${by[s] || 0}</div><div class="l">${esc(s.replaceAll('_', ' '))}</div></div>`).join('')}</div>
      <div class="card"><table><thead><tr><th>Reference</th><th>Borrower</th><th>Crop</th><th>Location</th><th class="num">Requested</th><th>Status</th></tr></thead><tbody>
      ${data.items.map((a) => `<tr class="click" data-id="${esc(a.id)}"><td>${esc(a.reference)}</td><td>${esc(a.group_name || a.borrower_pseudonym)}<div class="small muted">${esc(a.borrower_type.replaceAll('_', ' '))}</div></td>
        <td>${esc(a.primary_crop)}</td><td>${esc(a.region)}, ${esc(a.country)}</td><td class="num">${esc(fmtMoney(a.requested_amount, a.currency))}</td><td>${pill(a.status)}</td></tr>`).join('')}
      </tbody></table><p class="small muted">Synthetic applications. ${esc(data.total)} in your tenant.</p></div>`;
    $app.querySelectorAll('tr.click').forEach((tr) => tr.addEventListener('click', () => { location.hash = `#/finance/${tr.dataset.id}`; }));
  }

  const ACTIONS = { SUBMITTED: 'submit', IN_REVIEW: 'start_review', NEEDS_INFORMATION: 'request_information', APPROVED: 'approve', DECLINED: 'decline' };
  const ACTION_ROLE = { submit: 'finance analyst', start_review: 'finance analyst', request_information: 'finance reviewer', approve: 'finance reviewer', decline: 'finance reviewer' };

  async function financeDetail(id, tab = 'overview') {
    let app, analysis = null;
    try {
      app = await api(`/finance/applications/${id}`);
      if (app.latest_analysis_id) analysis = await api(`/finance/applications/${id}/analysis`);
    } catch (e) { $app.innerHTML = errBox(e); return; }
    const tabs = [['overview', 'Overview'], ['cash', 'Cash flow & scenarios'], ['risk', 'Risk & explanation'], ['evidence', 'Evidence & questions'], ['review', 'Review & decision'], ['audit', 'Audit trail']];
    $app.innerHTML = `<p><a href="#/finance">← Applications</a></p>
      <h1>${esc(app.group_name || app.borrower_pseudonym)} · ${esc(app.reference)} ${pill(app.status)}</h1>
      <div class="tabs">${tabs.map(([k, l]) => `<button data-tab="${k}" class="${k === tab ? 'on' : ''}">${l}</button>`).join('')}</div>
      <div id="tab"></div>`;
    $app.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => financeDetail(id, b.dataset.tab)));
    const $tab = document.getElementById('tab');
    const ccy = app.currency;
    const analyzeBtn = ['SUBMITTED', 'ANALYZED'].includes(app.status) && can('finance:analyze')
      ? '<button id="analyze">Run analysis</button>' : '';
    const wireAnalyze = () => {
      const b = document.getElementById('analyze');
      if (b) b.addEventListener('click', async () => { b.disabled = true; b.textContent = 'Analysing…'; try { await api(`/finance/applications/${id}/analyze`, { method: 'POST', body: {} }); financeDetail(id, 'cash'); } catch (e) { b.insertAdjacentHTML('afterend', errBox(e)); b.disabled = false; } });
    };

    if (tab === 'overview') {
      $tab.innerHTML = `<div class="tiles">
          <div class="tile"><div class="v">${esc(fmtMoney(app.requested_amount, ccy))}</div><div class="l">requested</div></div>
          <div class="tile"><div class="v">${esc(fmtNum(app.annual_interest_rate_pct))}%</div><div class="l">annual rate (declining balance)</div></div>
          <div class="tile"><div class="v">${esc(app.term_months)} months</div><div class="l">from ${esc(app.start_month)}</div></div>
          <div class="tile"><div class="v">${esc(app.repayment_type.replaceAll('_', ' '))}</div><div class="l">${app.repayment_months.length ? 'months ' + esc(app.repayment_months.join(', ')) : 'repayment'}</div></div></div>
        <div class="grid"><div class="card"><h2>Farm and borrower</h2><table>
          <tr><th>Pseudonymous ID</th><td>${esc(app.borrower_pseudonym)}</td></tr><tr><th>Type</th><td>${esc(app.borrower_type.replaceAll('_', ' '))}</td></tr>
          <tr><th>Location</th><td>${esc(app.locality || '')} ${esc(app.region)}, ${esc(app.country)}</td></tr><tr><th>Cultivated area</th><td>${esc(fmtNum(app.cultivated_area_ha))} ha</td></tr>
          <tr><th>Purpose</th><td>${esc(app.loan_purpose)}</td></tr><tr><th>Opening cash</th><td>${esc(fmtMoney(app.opening_cash_balance, ccy))}</td></tr>
          <tr><th>Existing obligations</th><td>${esc(fmtMoney(app.existing_obligations_monthly, ccy))} / month</td></tr>
          <tr><th>Other income / expenses</th><td>${esc(fmtMoney(app.other_monthly_income, ccy))} / ${esc(fmtMoney(app.operating_expenses_monthly, ccy))} per month</td></tr>
          <tr><th>Declared revenue / costs</th><td>${esc(fmtMoney(app.declared_annual_revenue, ccy))} / ${esc(fmtMoney(app.declared_production_costs, ccy))}</td></tr></table></div>
        <div class="card"><h2>Crop plan</h2><table><tr><th>Crop</th><th class="num">ha</th><th class="num">t/ha</th><th>basis</th><th class="num">price/t</th><th class="num">harvest month</th></tr>
          ${app.crops.map((c) => `<tr><td>${esc(c.crop)}</td><td class="num">${esc(fmtNum(c.area_ha))}</td><td class="num">${esc(fmtNum(c.expected_yield_t_per_ha))}</td><td>${esc(c.yield_basis)}</td><td class="num">${esc(fmtMoney(c.price_per_t))}</td><td class="num">${esc(c.harvest_month)}</td></tr>`).join('')}</table>
          <h3>Costs</h3><table><tr><th>Item</th><th>kind</th><th class="num">amount</th><th class="num">month</th></tr>
          ${app.costs.map((c) => `<tr><td>${esc(c.category)}</td><td>${esc(c.kind)}</td><td class="num">${esc(fmtMoney(c.amount))}</td><td class="num">${esc(c.month)}</td></tr>`).join('')}</table></div></div>
        <div class="row">${analyzeBtn}${app.status === 'DRAFT' ? '<span class="muted small">Submit the application (Review tab) before analysis.</span>' : ''}</div>`;
      wireAnalyze();
    }

    if (tab === 'cash') {
      if (!analysis) { $tab.innerHTML = `<div class="card"><p>No analysis yet.</p>${analyzeBtn}</div>`; wireAnalyze(); return; }
      const all = [analysis.baseline, ...analysis.scenarios];
      const s = analysis.baseline.summary;
      $tab.innerHTML = `<div class="tiles">
          <div class="tile"><div class="v">${esc(fmtMoney(s.harvest_revenue, ccy))}</div><div class="l">harvest revenue</div></div>
          <div class="tile"><div class="v">${esc(fmtMoney(s.production_costs, ccy))}</div><div class="l">production costs</div></div>
          <div class="tile"><div class="v">${esc(fmtMoney(s.new_loan_debt_service, ccy))}</div><div class="l">debt service (interest ${esc(fmtMoney(s.interest_total))})</div></div>
          <div class="tile"><div class="v">${esc(s.repayment_coverage_ratio ?? '—')}</div><div class="l">repayment coverage</div></div>
          <div class="tile"><div class="v">${esc(fmtMoney(s.minimum_closing_balance, ccy))}</div><div class="l">lowest balance (${esc(s.minimum_balance_month)})</div></div></div>
        <div class="card"><div class="row"><h2 style="margin:0">Monthly cash flow</h2><select id="scen">${all.map((r, i) => `<option value="${i}">${esc(r.scenario.label)}</option>`).join('')}</select></div><div id="chart"></div></div>
        <div class="card"><h2>Scenarios</h2><table><tr><th>Scenario</th><th class="num">Revenue</th><th class="num">Coverage</th><th class="num">Lowest balance</th><th>Negative months</th><th>Instalments uncovered</th></tr>
          ${all.map((r) => `<tr><td>${esc(r.scenario.label)}</td><td class="num">${esc(fmtMoney(r.summary.harvest_revenue))}</td><td class="num">${esc(r.summary.repayment_coverage_ratio ?? '—')}</td>
            <td class="num">${esc(fmtMoney(r.summary.minimum_closing_balance))}</td><td>${esc(r.summary.months_with_negative_balance.join(', ') || '—')}</td>
            <td>${esc(r.installments.filter((i) => !i.covered).map((i) => i.label).join(', ') || '—')}</td></tr>`).join('')}</table>
          <h3>What-if</h3><div class="row">
            <label>Yield % <input id="wy" type="number" value="-10" style="width:70px"></label><label>Price % <input id="wp" type="number" value="0" style="width:70px"></label>
            <label>Input cost % <input id="wc" type="number" value="0" style="width:70px"></label><label>Harvest delay (months) <input id="wd" type="number" value="0" min="0" max="12" style="width:60px"></label>
            ${can('finance:analyze') ? '<button id="whatif">Simulate</button>' : '<span class="small muted">Analysts can run simulations.</span>'}</div><div id="whatifOut"></div>
          <div class="notice">${analysis.assumptions.map(esc).join('<br>')}<br>Engine ${esc(analysis.engine_version)} · rules ${esc(analysis.rule_version)}</div></div>`;
      const draw = (i) => { document.getElementById('chart').innerHTML = cashChart(all[i].months, ccy); };
      draw(0);
      document.getElementById('scen').addEventListener('change', (e) => draw(+e.target.value));
      const w = document.getElementById('whatif');
      if (w) w.addEventListener('click', async () => {
        const out = document.getElementById('whatifOut');
        try {
          const r = await api(`/finance/applications/${id}/simulate`, { method: 'POST', body: { include_baseline: false, scenarios: [{ name: 'what-if', yield_change_pct: +document.getElementById('wy').value, price_change_pct: +document.getElementById('wp').value, input_cost_change_pct: +document.getElementById('wc').value, harvest_delay_months: +document.getElementById('wd').value }] } });
          const res = r.results[0];
          out.innerHTML = `<p class="okmsg">${esc(res.scenario.label)}: coverage <strong>${esc(res.summary.repayment_coverage_ratio ?? '—')}</strong>, lowest balance <strong>${esc(fmtMoney(res.summary.minimum_closing_balance, ccy))}</strong>${res.warnings.length ? '<br>' + res.warnings.map(esc).join('<br>') : ''}</p>${cashChart(res.months, ccy)}`;
        } catch (e) { out.innerHTML = errBox(e); }
      });
    }

    if (tab === 'risk') {
      if (!analysis) { $tab.innerHTML = `<div class="card"><p>No analysis yet.</p>${analyzeBtn}</div>`; wireAnalyze(); return; }
      const ob = analysis.indicators.obligation_burden;
      $tab.innerHTML = `<div class="card"><h2>Advisory risk flags</h2>${analysis.flags.length ? analysis.flags.map((f) => `<div class="flag ${esc(f.severity)}"><strong>${esc(f.title)}</strong> ${pill(f.severity)}<div class="small">${esc(f.explanation)}</div></div>`).join('') : '<p>No flags raised.</p>'}
          <p class="small muted">Rules ${esc(analysis.rule_version)}. Flags use financial, agronomic and documentary inputs only; no personal attributes are collected.</p></div>
        <div class="card"><h2>AI explanation <span class="small muted">(${esc(analysis.model_provider)} / ${esc(analysis.model_name)} · grounding: ${esc(analysis.explanation_grounding.mode)})</span></h2>
          <div class="answer">${esc(analysis.explanation)}</div>
          ${analysis.citations.map((c) => `<div class="cite">[${esc(c.n)}] ${esc(c.title)}${c.page ? ', page ' + esc(c.page) : ''} — <code>${esc(c.chunk_reference)}</code></div>`).join('')}
          <div class="notice">${esc(analysis.advisory_notice)}</div></div>
        <div class="card"><h2>Retail-credit benchmark (reused from the Banking Copilot)</h2>
          <p>Average-month obligations / income: <strong>${esc(ob.ratio_pct ?? '—')}%</strong> ${pill(ob.band, 'warning')}</p><p class="small muted">${esc(ob.caveat)} Source: ${esc(ob.source)}</p></div>
        <div class="row">${analyzeBtn}</div>`;
      wireAnalyze();
    }

    if (tab === 'evidence') {
      const types = ['farm_business_plan', 'yield_or_sales_evidence', 'land_use_evidence', 'cooperative_record', 'input_quotation', 'other_evidence'];
      $tab.innerHTML = `<div class="grid"><div class="card"><h2>Documents on file</h2><table><tr><th>Title</th><th>Type</th><th class="num">Chunks</th><th></th></tr>
          ${app.documents.map((d) => `<tr><td>${esc(d.title)}<div class="small muted">${esc(d.filename)}</div></td><td>${esc(d.document_type.replaceAll('_', ' '))}</td><td class="num">${esc(d.chunk_count)}</td><td>${d.flags.length ? pill('instruction-like text', 'high') : ''}</td></tr>`).join('') || '<tr><td colspan="4">None</td></tr>'}</table>
          ${can('finance:documents') ? `<h3>Upload evidence</h3><div class="row"><input type="file" id="file" accept=".pdf,.docx,.md,.txt,.csv"><select id="dtype">${types.map((t) => `<option>${t}</option>`).join('')}</select><button id="up">Upload</button></div><div id="upOut"></div>` : ''}</div>
        <div class="card"><h2>Ask the documents</h2><p class="small muted">Answers come only from this application's documents, with citations; otherwise the assistant abstains.</p>
          <div class="row"><input id="q" style="flex:1" value="What yields did the cooperative achieve in past seasons?"><button id="ask">Ask</button></div><div id="ans"></div></div></div>`;
      document.getElementById('ask').addEventListener('click', async () => {
        const out = document.getElementById('ans');
        out.innerHTML = '<p class="muted">Searching…</p>';
        try {
          const a = await api(`/finance/applications/${id}/ask`, { method: 'POST', body: { question: document.getElementById('q').value } });
          out.innerHTML = `<div class="answer">${esc(a.answer)}</div>${a.citations.map((c) => `<div class="cite">[${esc(c.n)}] ${esc(c.title)}${c.page ? ', p.' + esc(c.page) : ''}: “${esc(c.excerpt)}…”</div>`).join('')}
            ${a.excluded_flagged.length ? `<div class="flag high small">${a.excluded_flagged.length} passage(s) with instruction-like text were excluded from the model's context.</div>` : ''}`;
        } catch (e) { out.innerHTML = errBox(e); }
      });
      const up = document.getElementById('up');
      if (up) up.addEventListener('click', async () => {
        const f = document.getElementById('file').files[0];
        const out = document.getElementById('upOut');
        if (!f) { out.innerHTML = '<div class="err">Choose a file.</div>'; return; }
        const form = new FormData(); form.append('file', f); form.append('document_type', document.getElementById('dtype').value);
        try { const d = await api(`/finance/applications/${id}/documents`, { method: 'POST', form }); out.innerHTML = `<div class="okmsg">Indexed ${esc(d.chunk_count)} chunks${d.created ? '' : ' (already on file)'}.</div>`; setTimeout(() => financeDetail(id, 'evidence'), 900); } catch (e) { out.innerHTML = errBox(e); }
      });
    }

    if (tab === 'review') {
      const options = app.allowed_transitions.filter((s) => ACTIONS[s]);
      const evidence = [...app.documents.map((d) => ({ id: `document:${d.id}`, label: d.title })), ...(analysis ? [{ id: `analysis:${analysis.id}`, label: `Analysis v${analysis.version}` }] : [])];
      $tab.innerHTML = `<div class="card"><h2>Human review</h2>
        <p>Current state ${pill(app.status)}. ${app.status === 'SUBMITTED' ? 'Run the analysis next (Overview tab).' : ''}</p>
        ${options.length ? `<p class="small muted">Approve and decline can only be recorded by a finance reviewer who did not prepare the application, with a reason and the evidence reviewed. The AI cannot set these states.</p>
          <label class="small">Reason</label><textarea id="reason" placeholder="Reason for this decision"></textarea>
          <h3>Evidence reviewed</h3>${evidence.map((e) => `<div><label><input type="checkbox" class="ev" value="${esc(e.id)}"> ${esc(e.label)}</label></div>`).join('')}
          <div class="row">${options.map((s) => `<button data-to="${s}" class="${s === 'DECLINED' ? 'danger' : s === 'NEEDS_INFORMATION' ? 'secondary' : ''}">${esc(ACTIONS[s].replaceAll('_', ' '))}</button><span class="small muted">(${ACTION_ROLE[ACTIONS[s]]})</span>`).join('')}</div>`
        : '<p>No further actions. This is a final state or the next step is analysis.</p>'}<div id="revOut"></div></div>`;
      $tab.querySelectorAll('button[data-to]').forEach((b) => b.addEventListener('click', async () => {
        const out = document.getElementById('revOut');
        try {
          const r = await api(`/finance/applications/${id}/review`, { method: 'POST', body: { action: ACTIONS[b.dataset.to], reason: document.getElementById('reason').value || null, evidence_refs: [...document.querySelectorAll('.ev:checked')].map((c) => c.value) } });
          out.innerHTML = `<div class="okmsg">Recorded ${esc(r.previous_state)} → ${esc(r.status)} by ${esc(r.recorded_by)} (audit event ${esc(r.audit_event_id)}).</div>`;
          setTimeout(() => financeDetail(id, 'review'), 1200);
        } catch (e) { out.innerHTML = errBox(e); }
      }));
    }

    if (tab === 'audit') {
      try {
        const a = await api(`/finance/applications/${id}/audit`);
        $tab.innerHTML = `<div class="card"><h2>Decision provenance</h2><ol class="timeline">${a.decisions.map((d) => `<li>${pill(d.from_state)} → ${pill(d.to_state)} by <strong>${esc(d.actor)}</strong> (${esc(d.actor_kind)}, ${esc(d.actor_roles.join(', '))}) at ${esc(d.decided_at.slice(0, 19).replace('T', ' '))}
            ${d.reason ? `<div class="small">Reason: ${esc(d.reason)}</div>` : ''}${d.evidence_refs.length ? `<div class="small muted">Evidence: ${d.evidence_refs.map(esc).join(', ')}</div>` : ''}<div class="small muted">Versions: ${esc(JSON.stringify(d.versions))}</div></li>`).join('')}</ol></div>
          <div class="card"><h2>Audit events (hash-chained)</h2><table><tr><th>#</th><th>When</th><th>Event</th><th>Actor</th><th>Hash</th></tr>
            ${a.events.map((e) => `<tr><td>${esc(e.id)}</td><td class="small">${esc(e.occurred_at.slice(0, 19).replace('T', ' '))}</td><td>${esc(e.event_type)}</td><td>${esc(e.actor)}</td><td><code>${esc(e.hash.slice(0, 12))}…</code></td></tr>`).join('')}</table></div>`;
      } catch (e) { $tab.innerHTML = errBox(e); }
    }
  }

  // ------------------------------------------------------------------------------------------------ projects
  async function projectList() {
    let data;
    try { data = await api('/projects?limit=100'); } catch (e) { $app.innerHTML = `<h1>Project monitoring</h1>${errBox(e)}`; return; }
    $app.innerHTML = `<h1>Project monitoring</h1><div class="card"><table><thead><tr><th>Code</th><th>Project</th><th>Country</th><th class="num">Financing</th><th>Period</th><th class="num">Sites</th></tr></thead><tbody>
      ${data.items.map((p) => `<tr class="click" data-id="${esc(p.id)}"><td>${esc(p.code)}</td><td>${esc(p.name)}<div class="small muted">${esc(p.theme.replaceAll('_', ' '))}</div></td><td>${esc(p.country)}</td>
        <td class="num">${esc(fmtMoney(p.financing_amount, p.currency))}</td><td class="small">${esc(p.start_date)} → ${esc(p.end_date)}</td><td class="num">${esc(p.site_count)}</td></tr>`).join('')}
      </tbody></table><p class="small muted">Fictional demonstration projects you are assigned to (${esc(data.total)}). <a href="#/map">View on the map →</a></p></div>`;
    $app.querySelectorAll('tr.click').forEach((tr) => tr.addEventListener('click', () => { location.hash = `#/projects/${tr.dataset.id}`; }));
  }

  async function projectDetail(id, tab = 'overview') {
    let p;
    try { p = await api(`/projects/${id}`); } catch (e) { $app.innerHTML = errBox(e); return; }
    const tabs = [['overview', 'Overview'], ['milestones', 'Milestones'], ['budget', 'Budget'], ['indicators', 'Indicators'], ['reports', 'Reports'], ['documents', 'Documents & questions'], ['brief', 'Brief & review'], ['audit', 'Audit trail']];
    $app.innerHTML = `<p><a href="#/projects">← Projects</a></p><h1>${esc(p.name)} <span class="muted small">${esc(p.code)} · ${esc(p.country)}</span></h1>
      <div class="tabs">${tabs.map(([k, l]) => `<button data-tab="${k}" class="${k === tab ? 'on' : ''}">${l}</button>`).join('')}</div><div id="tab"><p class="muted">Loading…</p></div>`;
    $app.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => projectDetail(id, b.dataset.tab)));
    const $tab = document.getElementById('tab');
    const ccy = p.currency;
    try {
      if (tab === 'overview') {
        $tab.innerHTML = `<div class="grid"><div class="card"><h2>Programme</h2><p>${esc(p.programme_name)}</p><p class="small">${esc(p.implementing_organization)}</p>
            <table><tr><th>Financing</th><td>${esc(fmtMoney(p.financing_amount, ccy))}</td></tr><tr><th>Period</th><td>${esc(p.start_date)} → ${esc(p.end_date)}</td></tr><tr><th>Reporting as of</th><td>${esc(p.reporting_as_of)}</td></tr></table>
            <h3>Objectives</h3><ul>${p.objectives.map((o) => `<li>${esc(o)}</li>`).join('')}</ul><h3>Expected results</h3><ul>${p.expected_results.map((o) => `<li>${esc(o)}</li>`).join('')}</ul></div>
          <div class="card"><h2>Sites</h2><table><tr><th>Site</th><th>Location</th><th class="num">Reached / target</th></tr>${p.sites.map((s) => `<tr><td>${esc(s.site_name)}<div class="small muted">${esc(s.activity_type)}</div></td><td>${esc(s.city)}, ${esc(s.region)}</td><td class="num">${esc(fmtNum(s.beneficiaries_reached))} / ${esc(fmtNum(s.beneficiaries_target))}</td></tr>`).join('')}</table>
          <p><a href="#/map?country=${encodeURIComponent(p.country)}">Show on map →</a></p></div></div>
          <div class="card"><h2>Delay and evidence checks</h2>${can('project:analyze') ? '<button id="run">Run checks</button>' : '<p class="small muted">Project analysts can run the checks.</p>'}<div id="flags"></div></div>`;
        const b = document.getElementById('run');
        if (b) b.addEventListener('click', async () => {
          const r = await api(`/projects/${id}/analyze`, { method: 'POST' });
          document.getElementById('flags').innerHTML = `<p>Progress <strong>${esc(r.progress.actual_pct)}%</strong> vs <strong>${esc(r.progress.planned_pct)}%</strong> planned (gap ${esc(r.progress.gap_pp)} pp) · ${esc(r.time_elapsed_pct)}% of time elapsed</p>
            ${r.flags.map((f) => `<div class="flag ${esc(f.severity)}"><strong>${esc(f.title)}</strong> ${pill(f.severity)}<div class="small">${esc(f.explanation)}</div></div>`).join('') || '<p>No flags.</p>'}<p class="small muted">Rules ${esc(r.rule_version)}</p>`;
        });
      }
      if (tab === 'milestones') {
        const m = await api(`/projects/${id}/milestones`);
        $tab.innerHTML = `<div class="tiles"><div class="tile"><div class="v">${esc(m.progress.planned_pct)}%</div><div class="l">planned progress</div></div><div class="tile"><div class="v">${esc(m.progress.actual_pct)}%</div><div class="l">actual progress</div></div><div class="tile"><div class="v">${esc(m.progress.gap_pp)} pp</div><div class="l">schedule gap (as of ${esc(m.as_of)})</div></div></div>
          <div class="card"><table><tr><th>Code</th><th>Activity</th><th class="num">Weight</th><th class="num">Planned</th><th class="num">Actual</th><th>Planned end</th><th>Status</th><th>Issues</th></tr>
          ${m.items.map((x) => `<tr><td>${esc(x.code)}</td><td>${esc(x.title)}<div class="small muted">${esc(x.component)} · ${esc(x.responsible_unit)}</div></td><td class="num">${esc(fmtNum(x.weight_pct))}%</td><td class="num">${esc(fmtNum(x.planned_progress_pct))}%</td><td class="num">${esc(fmtNum(x.actual_progress_pct))}%</td><td>${esc(x.planned_end)}</td><td>${pill(x.derived_status)}</td><td class="small">${x.issues.map((i) => esc(i.detail)).join('<br>') || '—'}</td></tr>`).join('')}</table></div>`;
      }
      if (tab === 'budget') {
        const b = await api(`/projects/${id}/budget`);
        const t = b.totals, ev = b.earned_value;
        $tab.innerHTML = `<div class="tiles"><div class="tile"><div class="v">${esc(fmtMoney(t.budget, ccy))}</div><div class="l">budget</div></div><div class="tile"><div class="v">${esc(fmtMoney(t.committed, ccy))}</div><div class="l">committed (obligations)</div></div>
            <div class="tile"><div class="v">${esc(fmtMoney(t.actual_expenditure, ccy))}</div><div class="l">actual expenditure</div></div><div class="tile"><div class="v">${esc(ev.cpi ?? '—')} / ${esc(ev.spi ?? '—')}</div><div class="l">CPI / SPI</div></div>
            <div class="tile"><div class="v">${esc(fmtMoney(ev.estimate_at_completion, ccy))}</div><div class="l">estimate at completion</div></div></div>
          <div class="grid"><div class="card"><h2>By component</h2><table><tr><th>Component</th><th class="num">Budget</th><th class="num">Committed</th><th class="num">Spent</th><th class="num">Used</th></tr>
            ${b.components.map((c) => `<tr><td>${esc(c.component)} ${c.overspent ? pill('overspent', 'high') : ''}</td><td class="num">${esc(fmtMoney(c.budget))}</td><td class="num">${esc(fmtMoney(c.committed))}</td><td class="num">${esc(fmtMoney(c.actual_expenditure))}</td><td class="num">${esc(c.utilisation_pct)}%</td></tr>`).join('')}</table>
            <p class="small muted">${esc(b.definitions.committed)}. Actual expenditure: ${esc(b.definitions.actual_expenditure)}.</p></div>
          <div class="card"><h2>Spending by quarter</h2>${barChart(b.spending_by_period.map((x) => ({ label: x.period, value: x.amount })), ccy)}
            <p class="small">Average of last ${esc(b.spending_velocity.window)} quarters: ${esc(fmtMoney(b.spending_velocity.average_per_period, ccy))}; remaining budget lasts ~${esc(b.spending_velocity.periods_to_exhaust_at_average)} quarters at that pace.</p>
            <p class="small muted">Forecast method: ${esc(b.spending_forecast.method || b.spending_forecast.status)}. ${esc(b.spending_forecast.note || '')}</p></div></div>`;
      }
      if (tab === 'indicators') {
        const ind = await api(`/projects/${id}/indicators`);
        $tab.innerHTML = `<div class="card"><table><tr><th>Indicator</th><th>Level</th><th class="num">Baseline</th><th class="num">Target</th><th class="num">Actual</th><th class="num">Attainment</th><th>Verification</th><th>Warnings</th></tr>
          ${ind.items.map((i) => `<tr><td>${esc(i.name)}<div class="small muted">${esc(i.unit)} · ${esc(i.reporting_period || 'not reported')} · ${esc(i.data_source || 'no source')}</div></td><td>${esc(i.level)}</td><td class="num">${esc(fmtNum(i.baseline))}</td><td class="num">${esc(fmtNum(i.target))}</td><td class="num">${esc(fmtNum(i.actual))}</td>
            <td class="num">${i.attainment_pct === null ? '—' : esc(i.attainment_pct) + '%'}${i.gap_to_expected_pp && +i.gap_to_expected_pp >= 15 ? ' ' + pill('behind plan', 'warning') : ''}</td><td>${pill(i.verification_status)}</td><td class="small">${i.quality_warnings.map(esc).join('<br>')}</td></tr>`).join('')}</table>
          <p class="small muted">Output delivery expected by now: ${esc(ind.expected_output_delivery_pct)}% (planned progress). Attainment is not evidence of impact.</p></div>`;
      }
      if (tab === 'reports') {
        const r = await api(`/projects/${id}/reports`);
        $tab.innerHTML = `<div class="tiles"><div class="tile"><div class="v">${esc(r.completeness_pct)}%</div><div class="l">reporting completeness</div></div><div class="tile"><div class="v">${esc(r.missing.length)}</div><div class="l">missing reports</div></div><div class="tile"><div class="v">${esc(r.late)}</div><div class="l">received late</div></div></div>
          <div class="card"><table><tr><th>Type</th><th>Period</th><th>Due</th><th>Received</th></tr>${r.reports.map((x) => `<tr><td>${esc(x.report_type.replaceAll('_', ' '))}</td><td>${esc(x.period)}</td><td>${esc(x.due_date)}</td><td>${x.received_date ? esc(x.received_date) : pill('missing', 'high')}</td></tr>`).join('')}</table></div>`;
      }
      if (tab === 'documents') {
        const docs = await api(`/projects/${id}/documents`);
        const types = ['progress_report', 'supervision_report', 'financial_report', 'field_report', 'evidence_record'];
        $tab.innerHTML = `<div class="grid"><div class="card"><h2>Documents</h2><table><tr><th>Title</th><th>Type</th><th>Period</th><th></th></tr>${docs.items.map((d) => `<tr><td>${esc(d.title)}</td><td>${esc(d.document_type.replaceAll('_', ' '))}</td><td>${esc(d.reporting_period || '')}</td><td>${d.flags.length ? pill('instruction-like text', 'high') : ''}</td></tr>`).join('')}</table>
            ${can('project:documents') ? `<h3>Upload a report</h3><div class="row"><input type="file" id="file" accept=".pdf,.docx,.md,.txt,.csv"><select id="dtype">${types.map((t) => `<option>${t}</option>`).join('')}</select></div>
            <div class="row"><input id="period" placeholder="Period e.g. 2025-Q4" style="width:150px"><input id="rtype" placeholder="Report type to mark received (optional)" style="width:240px"><input id="mcode" placeholder="Milestone code (optional)" style="width:170px"><button id="up">Upload</button></div><div id="upOut"></div>` : ''}</div>
          <div class="card"><h2>Ask the project documents</h2><div class="row"><input id="q" style="flex:1" value="What caused the construction delays?"><button id="ask">Ask</button></div><div id="ans"></div></div></div>`;
        document.getElementById('ask').addEventListener('click', async () => {
          const out = document.getElementById('ans');
          try {
            const a = await api(`/projects/${id}/ask`, { method: 'POST', body: { question: document.getElementById('q').value } });
            out.innerHTML = `<div class="answer">${esc(a.answer)}</div>${a.citations.map((c) => `<div class="cite">[${esc(c.n)}] ${esc(c.title)}${c.page ? ', p.' + esc(c.page) : ''}</div>`).join('')}${a.excluded_flagged.length ? `<div class="flag high small">${a.excluded_flagged.length} passage(s) with instruction-like text were excluded.</div>` : ''}`;
          } catch (e) { out.innerHTML = errBox(e); }
        });
        const up = document.getElementById('up');
        if (up) up.addEventListener('click', async () => {
          const f = document.getElementById('file').files[0];
          const out = document.getElementById('upOut');
          if (!f) { out.innerHTML = '<div class="err">Choose a file.</div>'; return; }
          const form = new FormData();
          form.append('file', f); form.append('document_type', document.getElementById('dtype').value);
          [['reporting_period', 'period'], ['report_type', 'rtype'], ['milestone_code', 'mcode']].forEach(([k, el]) => { const v = document.getElementById(el).value.trim(); if (v) form.append(k, v); });
          try { const d = await api(`/projects/${id}/documents`, { method: 'POST', form }); out.innerHTML = `<div class="okmsg">Indexed ${esc(d.chunk_count)} chunks. Links: ${esc(JSON.stringify(d.links))}</div>`; } catch (e) { out.innerHTML = errBox(e); }
        });
      }
      if (tab === 'brief') {
        const list = (await api(`/projects/${id}/briefs`)).items;
        const b = list[0];
        const map = { SUBMITTED: 'submit', CHANGES_REQUESTED: 'request_changes', APPROVED: 'approve' };
        $tab.innerHTML = `<div class="card"><div class="row"><h2 style="margin:0">Project brief</h2>${can('project:brief') ? '<button id="gen">Generate new draft</button>' : ''}</div><div id="genOut"></div>
          ${b ? `<p>Version ${esc(b.version)} ${pill(b.status)} · ${esc(b.model_provider)}/${esc(b.model_name)} · grounding ${esc(b.grounding.mode)} · evidence support ${esc(Math.round(b.grounding.evidence_support.supported_ratio * 100))}%</p>
            <div class="answer">${esc(b.narrative)}</div>${b.citations.map((c) => `<div class="cite">[${esc(c.n)}] ${esc(c.title)}${c.page ? ', p.' + esc(c.page) : ''}</div>`).join('')}
            <h3>Suggested next review actions</h3><ul>${b.sections.suggested_next_review_actions.map((a) => `<li>${esc(a)}</li>`).join('')}</ul>
            <h3>Indicators requiring verification</h3><p class="small">${b.sections.indicators_requiring_verification.map((i) => `${esc(i.code)} ${esc(i.name)} (${esc(i.status)})`).join('; ') || 'None'}</p>
            <div class="notice">${esc(b.notice)} ${esc(b.sections.disclaimer)}</div>
            ${b.allowed_transitions.length ? `<h3>Review</h3><textarea id="reason" placeholder="Reason"></textarea><div class="row">${b.allowed_transitions.map((s) => `<button data-to="${s}" class="${s === 'CHANGES_REQUESTED' ? 'secondary' : ''}">${esc(map[s].replaceAll('_', ' '))}</button>`).join('')}<span class="small muted">Approval: project reviewer, with reason; the citations are recorded as evidence reviewed.</span></div>` : ''}<div id="revOut"></div>`
            : '<p class="muted">No brief yet.</p>'}</div>`;
        const g = document.getElementById('gen');
        if (g) g.addEventListener('click', async () => { g.disabled = true; g.textContent = 'Generating…'; try { await api(`/projects/${id}/brief`, { method: 'POST' }); projectDetail(id, 'brief'); } catch (e) { document.getElementById('genOut').innerHTML = errBox(e); g.disabled = false; } });
        $tab.querySelectorAll('button[data-to]').forEach((btn) => btn.addEventListener('click', async () => {
          try {
            const r = await api(`/projects/${id}/review`, { method: 'POST', body: { brief_id: b.id, action: map[btn.dataset.to], reason: document.getElementById('reason').value || null, evidence_refs: b.citations.map((c) => c.chunk_reference) } });
            document.getElementById('revOut').innerHTML = `<div class="okmsg">${esc(r.previous_state)} → ${esc(r.status)} by ${esc(r.recorded_by)}</div>`;
            setTimeout(() => projectDetail(id, 'brief'), 1000);
          } catch (e) { document.getElementById('revOut').innerHTML = errBox(e); }
        }));
      }
      if (tab === 'audit') {
        const a = await api(`/projects/${id}/audit`);
        $tab.innerHTML = `<div class="card"><h2>Brief decisions</h2><ol class="timeline">${a.decisions.map((d) => `<li>${pill(d.from_state)} → ${pill(d.to_state)} by <strong>${esc(d.actor)}</strong> at ${esc(d.decided_at.slice(0, 19).replace('T', ' '))}${d.reason ? `<div class="small">${esc(d.reason)}</div>` : ''}</li>`).join('') || '<li class="muted">None yet</li>'}</ol></div>
          <div class="card"><h2>Audit events</h2><table><tr><th>#</th><th>When</th><th>Event</th><th>Actor</th></tr>${a.events.map((e) => `<tr><td>${esc(e.id)}</td><td class="small">${esc(e.occurred_at.slice(0, 19).replace('T', ' '))}</td><td>${esc(e.event_type)}</td><td>${esc(e.actor)}</td></tr>`).join('')}</table></div>`;
      }
    } catch (e) { $tab.innerHTML = errBox(e); }
  }

  // ------------------------------------------------------------------------------------------------ map
  let leaflet = null;
  async function mapView(params) {
    const q = new URLSearchParams(params);
    let data;
    try { data = await api(`/projects/map?${q}`); } catch (e) { $app.innerHTML = `<h1>Project map</h1>${errBox(e)}`; return; }
    const facets = data.facets.countries;
    const country = q.get('country') || '', region = q.get('region') || '', city = q.get('city') || '';
    const regions = (facets.find((c) => c.country === country)?.regions) || [];
    const cities = (regions.find((r) => r.region === region)?.cities) || [];
    const opt = (vals, cur, all) => `<option value="">${all}</option>` + vals.map((v) => `<option ${v === cur ? 'selected' : ''}>${esc(v)}</option>`).join('');
    $app.innerHTML = `<h1>Project map</h1>
      <div class="row"><select id="fc">${opt(facets.map((c) => c.country), country, 'All countries')}</select>
        <select id="fr" ${country ? '' : 'disabled'}>${opt(regions.map((r) => r.region), region, 'All regions')}</select>
        <select id="fi" ${region ? '' : 'disabled'}>${opt(cities, city, 'All cities')}</select>
        ${can('finance:read') ? '<label class="small"><input type="checkbox" id="loans"> show loan applications</label>' : ''}</div>
      <div class="cols"><div class="card"><h2>By ${esc(data.level)}</h2><table><tr><th>${esc(data.level)}</th><th class="num">Sites</th><th class="num">Reached / target</th></tr>
        ${data.aggregates.map((a) => `<tr class="click" data-name="${esc(a.name)}"><td>${esc(a.name)}<div class="small muted">${a.projects.map(esc).join(', ')}</div></td><td class="num">${esc(a.sites)}</td><td class="num">${esc(fmtNum(a.beneficiaries_reached))} / ${esc(fmtNum(a.beneficiaries_target))}</td></tr>`).join('')}</table>
        <p class="small muted">${esc(data.note)}</p></div>
        <div><div id="map"></div></div></div>`;
    const go = (c, r, ci) => { const p = new URLSearchParams(); if (c) p.set('country', c); if (r) p.set('region', r); if (ci) p.set('city', ci); location.hash = `#/map?${p}`; };
    document.getElementById('fc').addEventListener('change', (e) => go(e.target.value));
    document.getElementById('fr').addEventListener('change', (e) => go(country, e.target.value));
    document.getElementById('fi').addEventListener('change', (e) => go(country, region, e.target.value));
    $app.querySelectorAll('tr.click').forEach((tr) => tr.addEventListener('click', () => {
      if (data.level === 'country') go(tr.dataset.name); else if (data.level === 'region') go(country, tr.dataset.name); else go(country, region, tr.dataset.name);
    }));
    if (!window.L) { document.getElementById('map').innerHTML = '<p class="muted" style="padding:12px">Map tiles need internet access; the table shows the same data.</p>'; return; }
    if (leaflet) { leaflet.remove(); leaflet = null; }
    leaflet = L.map('map');
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 12, attribution: '&copy; OpenStreetMap contributors' }).addTo(leaflet);
    const pts = [];
    data.sites.forEach((s) => {
      const r = 6 + Math.sqrt(s.beneficiaries_target) / 6;
      L.circleMarker([s.latitude, s.longitude], { radius: r, color: '#2f6b4f', fillOpacity: 0.55 }).addTo(leaflet)
        .bindPopup(`<strong>${esc(s.site_name)}</strong><br>${esc(s.city)}, ${esc(s.region)}, ${esc(s.country)}<br>${esc(s.activity_type)}<br>Reached ${esc(fmtNum(s.beneficiaries_reached))} / ${esc(fmtNum(s.beneficiaries_target))}<br><a href="#/projects/${esc(s.project_id)}">${esc(s.project_code)} ${esc(s.project_name)}</a>`);
      pts.push([s.latitude, s.longitude]);
    });
    if (pts.length) leaflet.fitBounds(pts, { padding: [30, 30], maxZoom: city ? 9 : 7 }); else leaflet.setView([5, 20], 2);
    const loans = document.getElementById('loans');
    let loanLayer = null;
    if (loans) loans.addEventListener('change', async () => {
      if (loanLayer) { loanLayer.remove(); loanLayer = null; }
      if (!loans.checked) return;
      const apps = await api('/finance/applications/map');
      loanLayer = L.layerGroup(apps.items.map((a) => L.circleMarker([a.latitude, a.longitude], { radius: 7, color: '#c0773a', fillOpacity: 0.7 })
        .bindPopup(`<strong>${esc(a.reference)}</strong> ${esc(a.status)}<br>${esc(a.primary_crop)} · ${esc(fmtMoney(a.requested_amount, a.currency))}<br><a href="#/finance/${esc(a.id)}">Open application</a><br><span class="small">${esc(apps.precision_note)}</span>`))).addTo(leaflet);
    });
  }

  // ------------------------------------------------------------------------------------------------ operations
  async function ops() {
    let health = null, status = null, evals = null, err = '';
    try { health = await (await fetch('/health')).json(); } catch { /* shown below */ }
    try { status = await api('/platform/status'); } catch (e) { err = errBox(e); }
    try { evals = await api('/evaluations/latest'); } catch { /* optional */ }
    $app.innerHTML = `<h1>Platform operations</h1>
      <div class="card"><h2>Gateway</h2><p>${health ? `${pill('ok')} ${esc(health.service)} ${esc(health.version)} · commit ${esc(health.commit_sha.slice(0, 7))} · ${esc(health.deployment_target)}` : pill('unreachable', 'high')}</p></div>
      ${status ? `<div class="grid">${status.services.map((s) => `<div class="card"><h2>${esc(s.service)} ${pill(s.ok ? 'ready' : 'not ready', s.ok ? 'ok' : 'high')}</h2>
          ${s.ready ? Object.entries(s.ready.checks).map(([k, v]) => `<div class="small">${esc(k)}: ${pill(v.ok ? 'ok' : 'fail', v.ok ? 'ok' : 'high')} ${esc(v.detail)}</div>`).join('') : `<div class="small">${esc(s.error || '')}</div>`}</div>`).join('')}
        <div class="card"><h2>Model</h2><p>${pill(status.model.ok ? 'ok' : 'down', status.model.ok ? 'ok' : 'high')} ${esc(status.model.provider)} / ${esc(status.model.model)}</p><p class="small">Embeddings: ${esc(status.model.embedding_model)} (${esc(status.model.embedding_dim)} dims)<br>${esc(status.model.detail)}</p></div>
        <div class="card"><h2>Storage</h2><p>${pill(status.storage.ok ? 'ok' : 'fail', status.storage.ok ? 'ok' : 'high')} ${esc(status.storage.backend)} — ${esc(status.storage.detail)}</p></div></div>
        <div class="card"><h2>Gateway request metrics</h2><p class="small">${esc(status.gateway.metrics.requests_total)} requests · ${esc(status.gateway.metrics.errors_5xx)} server errors · up ${esc(status.gateway.metrics.uptime_seconds)} s</p>
          <table><tr><th>Route</th><th class="num">Count</th><th class="num">p50 ms</th><th class="num">p95 ms</th></tr>${status.gateway.metrics.routes.slice(0, 15).map((r) => `<tr><td><code>${esc(r.route)}</code></td><td class="num">${esc(r.count)}</td><td class="num">${esc(r.p50_ms)}</td><td class="num">${esc(r.p95_ms)}</td></tr>`).join('')}</table>
          <h3>Recent errors</h3>${status.gateway.metrics.recent_errors.length ? `<table>${status.gateway.metrics.recent_errors.slice(-10).map((e) => `<tr><td class="small">${esc(e.at)}</td><td><code>${esc(e.path)}</code></td><td>${esc(e.status)}</td><td class="small">${esc(e.correlation_id)}</td></tr>`).join('')}</table>` : '<p class="small muted">None</p>'}</div>` : err}
      <div class="card"><h2>Latest evaluations</h2>${evals && evals.items.length ? `<table><tr><th>Suite</th><th>Dataset</th><th>Metrics</th><th>Result</th><th>When</th></tr>${evals.items.map((r) => `<tr><td>${esc(r.suite)}</td><td>${esc(r.dataset_version)}</td><td class="small">${esc(Object.entries(r.metrics).map(([k, v]) => `${k}=${v}`).join(', '))}</td><td>${pill(r.passed ? 'pass' : 'fail', r.passed ? 'ok' : 'high')}</td><td class="small">${esc(r.created_at.slice(0, 16))}</td></tr>`).join('')}</table>` : '<p class="small muted">No evaluation has been run yet (<code>make eval</code>).</p>'}</div>`;
  }

  // ------------------------------------------------------------------------------------------------ router
  async function route() {
    const [path, query] = (location.hash.slice(1) || '/').split('?');
    const parts = path.split('/').filter(Boolean);
    document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.getAttribute('href') === `#/${parts[0] || ''}`));
    $app.innerHTML = '<p class="muted">Loading…</p>';
    if (!parts.length) return home();
    if (parts[0] === 'finance') return parts[1] ? financeDetail(parts[1]) : financeList();
    if (parts[0] === 'projects') return parts[1] ? projectDetail(parts[1]) : projectList();
    if (parts[0] === 'map') return mapView(Object.fromEntries(new URLSearchParams(query || '')));
    if (parts[0] === 'ops') return ops();
    return home();
  }
  window.addEventListener('hashchange', route);
  initUsers().then(route).catch((e) => { $app.innerHTML = errBox(e); });
})();
