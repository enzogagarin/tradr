// --- Auth token handling ---
const __token = new URLSearchParams(window.location.search).get('token');
if (__token) localStorage.setItem('paz_token', __token);
const __authToken = localStorage.getItem('paz_token');
function authUrl(path) {
  return __authToken ? `${path}?token=${encodeURIComponent(__authToken)}` : path;
}

const state = {
  paused: false,
  selectedOutcome: 'UP',
  btcHistory: [],
  lastBtc: null,
  lastFeedKey: null,
  maxHistory: 120,
  latest: null,
  secsToClose: null,
  secsSyncAt: 0,
  feedRows: [],
  feedFilter: 'all',
  expanded: null,
  act: null,
  actSyncAt: 0,
};

// --- fetch helpers ---
async function loadSnapshot() {
  const r = await fetch(authUrl('/api/snapshot'), { cache: 'no-store' });
  if (!r.ok) throw new Error(`snapshot ${r.status}`);
  return r.json();
}
async function loadPerformance() {
  const r = await fetch(authUrl('/api/performance'), { cache: 'no-store' });
  if (!r.ok) throw new Error(`performance ${r.status}`);
  return r.json();
}

// --- formatters ---
const nf2 = (v) => (v == null || Number.isNaN(+v)) ? '--' : (+v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money = (v) => (v == null || Number.isNaN(+v)) ? '--' : `$${nf2(v)}`;
const price = (v) => (v == null || Number.isNaN(+v)) ? '--' : (+v).toFixed(2);
const cents = (v) => (v == null || Number.isNaN(+v)) ? '--' : `${(+v * 100).toFixed(0)}\u00A2`;
const pct = (v) => (v == null || Number.isNaN(+v)) ? '--' : `${(+v * 100).toFixed(0)}%`;
const pct1 = (v) => (v == null || Number.isNaN(+v)) ? '--' : `${(+v * 100).toFixed(1)}%`;
function setText(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }

// --- topbar ticker ---
function renderTicker(snapshot) {
  const p = Number(snapshot.btc_tick.price);
  const el = document.getElementById('btcPrice');
  setText('btcPrice', `$${nf2(p)}`);
  if (state.lastBtc != null && p !== state.lastBtc) {
    el.classList.remove('flash-up', 'flash-down');
    void el.offsetWidth;
    el.classList.add(p > state.lastBtc ? 'flash-up' : 'flash-down');
    setTimeout(() => el.classList.remove('flash-up', 'flash-down'), 500);
  }
  const ref = Number(snapshot.risk_state.reference_price);
  const diff = p - ref;
  const chEl = document.getElementById('btcChange');
  chEl.className = 'ticker-change ' + (diff >= 0 ? 'up' : 'down');
  setText('btcChange', `${diff >= 0 ? '▲' : '▼'} ${nf2(Math.abs(diff))} vs ref`);
  state.lastBtc = p;
}

// --- countdown ring ---
// Sync the authoritative value from the server, then let a local ticker
// decrement it every 250ms so the countdown is smooth and never frozen,
// independent of poll latency.
function syncCountdown(snapshot) {
  state.secsToClose = Math.max(0, Number(snapshot.market.seconds_to_close) || 0);
  state.secsSyncAt = performance.now();
}

function tickCountdown() {
  if (state.secsToClose == null) return;
  const elapsed = (performance.now() - state.secsSyncAt) / 1000;
  const secs = Math.max(0, Math.round(state.secsToClose - elapsed));
  const total = 300;
  const frac = Math.max(0, Math.min(1, secs / total));
  const circ = 2 * Math.PI * 52;
  const ring = document.getElementById('cdRing');
  if (ring) {
    ring.style.strokeDasharray = circ.toFixed(1);
    ring.style.strokeDashoffset = (circ * (1 - frac)).toFixed(1);
    ring.style.stroke = secs < 45 ? 'var(--red)' : secs < 90 ? 'var(--amber)' : 'var(--blue)';
  }
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  setText('countdownText', `${m}:${String(s).padStart(2, '0')}`);
}

// --- outcomes ---
function renderOutcomes(snapshot) {
  const pUp = Number(snapshot.decision.probability_up);
  const pDown = 1 - pUp;
  setText('upProb', pct(pUp));
  setText('downProb', pct(pDown));
  document.getElementById('upBar').style.width = `${(pUp * 100).toFixed(1)}%`;
  document.getElementById('downBar').style.width = `${(pDown * 100).toFixed(1)}%`;
  setText('upAsk', price(snapshot.up_book.best_ask));
  setText('upBid', price(snapshot.up_book.best_bid));
  setText('downAsk', price(snapshot.down_book.best_ask));
  setText('downBid', price(snapshot.down_book.best_bid));
  const dsum = (b) => b.reduce((s, l) => s + Number(l.size), 0);
  setText('upDepth', `depth ${nf2(dsum(snapshot.up_book.bids) + dsum(snapshot.up_book.asks))}`);
  setText('downDepth', `depth ${nf2(dsum(snapshot.down_book.bids) + dsum(snapshot.down_book.asks))}`);
}

// --- decision ---
function explanation(s) {
  const d = s.decision;
  if (d.action === 'BUY_UP') return `Model UP olasılığını ${pct1(d.probability_up)} görüyor, UP ask ${price(s.up_book.best_ask)}. Edge ${cents(d.edge)} lehte.`;
  if (d.action === 'BUY_DOWN') return `Model DOWN tarafını ucuz buluyor. UP olasılığı ${pct1(d.probability_up)}, DOWN ask ${price(s.down_book.best_ask)}. Edge ${cents(d.edge)}.`;
  const map = {
    edge_below_threshold: 'Fiyat farkı işlem açmaya yetmiyor.',
    stale_btc_tick: 'BTC verisi taze değil, giriş yok.',
    spread_too_wide: 'Spread çok geniş, maliyet fazla.',
    active_market_too_close_to_end: 'Market kapanışa çok yakın.',
    kill_switch_enabled: 'Kill switch açık.',
    cycle_analyzing: 'Cycle analiz fazında, trade açmıyor.',
    cycle_cooldown: 'Cycle cooldown fazında, yeni giriş yok.',
    cycle_trade_taken: 'Bu 10 dakikalık cycle için trade hakkı kullanıldı.',
  };
  const primary = (d.reason || '').split('|')[0];
  return map[primary] || map[d.reason] || `No-trade: ${d.reason}`;
}

function renderDecision(snapshot) {
  const d = snapshot.decision;
  setText('action', d.action.replace('_', ' '));
  setText('probability', pct(d.probability_up));
  setText('edge', cents(d.edge));
  setText('targetPrice', price(d.target_price));
  setText('plainReason', explanation(snapshot));
  const badge = document.getElementById('signalBadge');
  badge.className = 'pill ' + (d.action === 'BUY_UP' ? 'buy-up' : d.action === 'BUY_DOWN' ? 'buy-down' : '');
  setText('signalBadge', d.reason.split('|')[0]);
  drawGauge(Number(d.probability_up));
}

// --- market head ---
function renderHead(snapshot) {
  const r = snapshot.risk_state;
  setText('question', snapshot.market.question);
  setText('modeChip', snapshot.mode.toUpperCase());
  setText('stateSource', `state ${r.state_source}`);
  setText('bookSource', `book ${r.book_source}`);
  setText('scheduleReason', r.schedule_reason);
}

// --- risk + wallet ---
function renderRisk(snapshot) {
  const r = snapshot.risk_state;
  const rv = r.risk_validation || {};
  setText('risk', rv.approved === false || r.kill_switch ? 'Blocked' : 'Clear');
  setText('riskReason', rv.reason_code || '--');
  setText('marketExposure', `${money(r.open_exposure)} / ${money(r.max_market_exposure)}`);
  setText('tradeCount', `${r.trades_in_market || 0} / ${r.max_trades_per_market || '--'}`);
  const cycle = r.cycle || {};
  setText('cyclePhase', cycle.enabled ? (cycle.phase || '--') : 'OFF');
  const cycleBits = cycle.enabled
    ? `${fmtDuration(cycle.seconds_remaining)} left · ${cycle.trades_taken || 0}/${r.cycle_max_trades || 1} used`
    : 'disabled';
  setText('cycleDetail', cycleBits);
  setText('limits', `${money(r.max_order_notional)} order · ${money(r.max_market_exposure)} market · ${money(r.max_daily_loss)} daily loss`);
  const checks = rv.checks || {};
  const labels = {
    kill_switch_off: 'Kill switch off',
    order_notional_within_limit: 'Order size OK',
    market_exposure_within_limit: 'Exposure OK',
    daily_loss_within_limit: 'Daily loss OK',
    trade_count_within_limit: 'Trade count OK',
    market_open: 'Market open',
  };
  const g = document.getElementById('guardrails');
  if (g) g.innerHTML = Object.entries(labels).map(([k, l]) => {
    const ok = checks[k] !== false;
    return `<span class="${ok ? 'pass' : 'fail'}">${ok ? '✓' : '✕'} ${l}</span>`;
  }).join('');

  setText('walletEnabled', r.wallet_signal_enabled ? 'ON' : 'OFF');
  setText('walletMode', r.wallet_signal_mode || 'overlay');
  setText('walletPath', r.wallet_signal_path || 'none');
  setText('walletReason', snapshot.decision.reason || '--');
  setText('walletEdge', cents(snapshot.decision.edge));
}

// --- order books ---
function renderBook(id, book) {
  const el = document.getElementById(id);
  if (!el) return;
  const maxSize = Math.max(...book.bids.concat(book.asks).map((l) => Number(l.size)), 1);
  const rows = [`<div class="book-r head"><span>Side</span><span>Price</span><span>Size</span></div>`];
  book.asks.slice().reverse().forEach((l) => {
    rows.push(`<div class="book-r ask"><div class="depth-bg" style="width:${(l.size / maxSize * 100).toFixed(0)}%"></div><span>ASK</span><span>${price(l.price)}</span><span>${nf2(l.size)}</span></div>`);
  });
  book.bids.forEach((l) => {
    rows.push(`<div class="book-r bid"><div class="depth-bg" style="width:${(l.size / maxSize * 100).toFixed(0)}%"></div><span>BID</span><span>${price(l.price)}</span><span>${nf2(l.size)}</span></div>`);
  });
  el.innerHTML = rows.join('');
}

// --- gauge ---
// Size the drawing buffer from the element's CSS layout size (fixed by its
// .chart-box / .gauge-wrap parent) and only touch the buffer when it actually
// changes. Reading clientWidth/clientHeight (not getBoundingClientRect) and
// guarding the write prevents any canvas-size feedback loop, so containers
// stay perfectly still.
function setupCanvas(canvas) {
  const w = canvas.clientWidth || (canvas.parentElement ? canvas.parentElement.clientWidth : 300);
  const h = canvas.clientHeight || (canvas.parentElement ? canvas.parentElement.clientHeight : 150);
  const dpr = window.devicePixelRatio || 1;
  const bw = Math.max(1, Math.round(w * dpr));
  const bh = Math.max(1, Math.round(h * dpr));
  if (canvas.width !== bw) canvas.width = bw;
  if (canvas.height !== bh) canvas.height = bh;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

function drawGauge(p) {
  const canvas = document.getElementById('probabilityGauge');
  const { ctx, w, h } = setupCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h * 0.86, r = Math.min(w * 0.42, h * 0.74);
  ctx.lineWidth = 14; ctx.lineCap = 'round';
  ctx.strokeStyle = '#242c3a';
  ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 0); ctx.stroke();
  const grad = ctx.createLinearGradient(cx - r, 0, cx + r, 0);
  if (p >= 0.5) { grad.addColorStop(0, '#1a8f6a'); grad.addColorStop(1, '#2fd39a'); }
  else { grad.addColorStop(0, '#ff5f73'); grad.addColorStop(1, '#c93a4d'); }
  ctx.strokeStyle = grad;
  ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, Math.PI + Math.PI * p); ctx.stroke();
  ctx.fillStyle = '#8b95a7'; ctx.font = '11px Inter, sans-serif';
  ctx.fillText('DOWN', 6, h - 6);
  ctx.fillText('UP', w - 22, h - 6);
}

// --- line/area charts ---
function chartBase(canvas) {
  const { ctx, w, h } = setupCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = '#1c2230'; ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const y = (h / 4) * i;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  return { ctx, w, h };
}

function drawBtcChart() {
  const canvas = document.getElementById('btcChart');
  const { ctx, w, h } = chartBase(canvas);
  const pts = state.btcHistory;
  if (pts.length < 2) {
    ctx.fillStyle = '#8b95a7'; ctx.font = '13px Inter';
    ctx.fillText('Collecting ticks…', 16, 26);
    return;
  }
  const prices = pts.map((p) => p.btc);
  const refs = pts.map((p) => p.ref);
  const all = prices.concat(refs).filter(Number.isFinite);
  const min = Math.min(...all), max = Math.max(...all);
  const xy = (v, i) => [(i / (pts.length - 1)) * w, h - ((v - min) / Math.max(1e-6, max - min)) * (h - 24) - 12];
  const line = (arr, color, width) => {
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.beginPath();
    arr.forEach((v, i) => { const [x, y] = xy(v, i); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
  };
  ctx.setLineDash([4, 4]); line(refs, '#f0b542', 1.5); ctx.setLineDash([]);
  line(prices, '#5b8cff', 2);
  const [lx, ly] = xy(prices[prices.length - 1], prices.length - 1);
  ctx.fillStyle = '#5b8cff'; ctx.beginPath(); ctx.arc(lx, ly, 3.5, 0, Math.PI * 2); ctx.fill();
}

function drawEquityChart(equity) {
  const canvas = document.getElementById('equityChart');
  const { ctx, w, h } = chartBase(canvas);
  if (!equity || equity.length < 1) {
    ctx.fillStyle = '#8b95a7'; ctx.font = '13px Inter';
    ctx.fillText('No resolved trades yet…', 16, 26);
    return;
  }
  const vals = equity.map((e) => e.equity);
  const min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const n = equity.length;
  const xy = (v, i) => [(n === 1 ? 0.5 : i / (n - 1)) * w, h - ((v - min) / Math.max(1e-6, max - min)) * (h - 24) - 12];
  // zero line
  const [, zy] = xy(0, 0);
  ctx.strokeStyle = '#313a4c'; ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(0, zy); ctx.lineTo(w, zy); ctx.stroke(); ctx.setLineDash([]);
  const last = vals[vals.length - 1];
  const col = last >= 0 ? '#2fd39a' : '#ff5f73';
  // area
  ctx.beginPath();
  equity.forEach((e, i) => { const [x, y] = xy(e.equity, i); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  const [ex] = xy(last, n - 1);
  ctx.lineTo(ex, zy); ctx.lineTo(xy(vals[0], 0)[0], zy); ctx.closePath();
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, last >= 0 ? 'rgba(47,211,154,0.28)' : 'rgba(255,95,115,0.28)');
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = grad; ctx.fill();
  // line
  ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.beginPath();
  equity.forEach((e, i) => { const [x, y] = xy(e.equity, i); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.stroke();
  const [lx, ly] = xy(last, n - 1);
  ctx.fillStyle = col; ctx.beginPath(); ctx.arc(lx, ly, 3.5, 0, Math.PI * 2); ctx.fill();
}

// --- activity status ---
function fmtDuration(sec) {
  if (sec == null || sec < 0) return '--';
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}
function fmtAgo(sec) {
  if (sec == null || sec < 0) return '--';
  sec = Math.round(sec);
  if (sec < 2) return 'just now';
  if (sec < 60) return `${sec}s ago`;
  const m = Math.floor(sec / 60);
  return `${m}m ${sec % 60}s ago`;
}
function fmtClock(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--';
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

const STATE_LABEL = { live: 'LIVE', slow: 'SLOWING', stale: 'STALLED', idle: 'IDLE' };
function narrate(a) {
  if (!a || !a.last_action) return 'Waiting for the first decision…';
  if (a.activity_status === 'stale' || a.activity_status === 'idle')
    return 'No fresh decisions. The paper-run loop may be stopped.';
  const act = a.last_action;
  const filled = a.last_execution_status === 'FILLED';
  if (act === 'BUY_UP') return filled ? 'Bought UP · filled at top of book' : 'Signalled BUY UP';
  if (act === 'BUY_DOWN') return filled ? 'Bought DOWN · filled at top of book' : 'Signalled BUY DOWN';
  if (act === 'NO_TRADE') return 'Scanning market · no edge right now';
  return `Last: ${act}`;
}

function syncActivity(perf) {
  state.act = {
    status: perf.activity_status,
    uptime: perf.uptime_seconds,
    sinceLast: perf.seconds_since_last,
    started: perf.session_start,
    rate: perf.decisions_per_min,
    last_action: perf.last_action,
    last_execution_status: perf.last_execution_status,
  };
  state.actSyncAt = performance.now();
  tickActivity();
}

function tickActivity() {
  const a = state.act;
  const sec = document.querySelector('.activity');
  if (!a || !sec) return;
  const elapsed = (performance.now() - state.actSyncAt) / 1000;
  const uptime = a.uptime != null ? a.uptime + elapsed : null;
  const since = a.sinceLast != null ? a.sinceLast + elapsed : null;
  // Escalate status locally if last decision keeps aging.
  let status = a.status || 'idle';
  if (since != null) status = since <= 20 ? 'live' : since <= 90 ? 'slow' : 'stale';
  sec.className = 'activity ' + status;
  setText('actState', STATE_LABEL[status] || 'IDLE');
  setText('actNarr', narrate({ ...a, activity_status: status }));
  setText('actStarted', fmtClock(a.started));
  setText('actUptime', fmtDuration(uptime));
  setText('actLast', fmtAgo(since));
  setText('actRate', a.rate != null ? `${a.rate}/min` : '--');
}

// --- performance ---
function renderPerformance(perf) {
  syncActivity(perf);
  const pnlEl = document.getElementById('kpiPnl');
  pnlEl.className = perf.estimated_pnl >= 0 ? 'pos' : 'neg';
  setText('kpiPnl', (perf.estimated_pnl >= 0 ? '+' : '') + money(perf.estimated_pnl).replace('$', '$'));
  setText('kpiWinRate', perf.resolved_trades ? `${pct1(perf.win_rate)}` : '--');
  setText('kpiTrades', perf.total_trades ?? '--');
  setText('kpiFills', perf.total_fills ?? '--');
  setText('kpiNotional', money(perf.total_fill_notional));
  setText('kpiWallet', perf.wallet_enhanced_count ?? '--');
  const pend = perf.pending_trades ? ` · ${perf.pending_trades} pending` : '';
  setText('equityLast', perf.resolved_trades
    ? `${perf.wins}W / ${perf.losses}L${pend} · last ${money(perf.estimated_pnl)}`
    : (perf.pending_trades ? `${perf.pending_trades} trades awaiting candle close` : 'awaiting fills'));
  drawEquityChart(perf.equity_curve);
  renderFeed(perf.recent_decisions || []);
}

function renderFeed(rows) {
  const feed = document.getElementById('tradeFeed');
  if (!feed) return;
  if (rows) state.feedRows = rows;
  const all = state.feedRows || [];
  const topKey = all.length ? all[0].ts : null;
  const f = state.feedFilter;
  const filtered = all.filter((r) => {
    if (f === 'trades') return (r.action || '').startsWith('BUY');
    if (f === 'skips') return r.action === 'NO_TRADE';
    return true;
  });
  setText('feedCount', `${filtered.length} shown`);
  const html = filtered.slice(0, 40).map((r, i) => {
    const isNew = rows && topKey && topKey !== state.lastFeedKey && i === 0 && f !== 'skips';
    const act = r.action || '--';
    const tag = act === 'BUY_UP' ? 'up' : act === 'BUY_DOWN' ? 'down' : 'flat';
    const st = r.execution_status === 'FILLED' ? 'filled' : 'skip';
    const expanded = state.expanded === r.ts;
    // Per-trade P&L: resolved win/loss (colored) or pending until candle closes.
    let pnlCell = '<span>--</span>';
    if ((act || '').startsWith('BUY') && r.execution_status === 'FILLED') {
      if (r.resolved && r.pnl != null) {
        const cls = r.pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
        pnlCell = `<span class="${cls}">${r.pnl >= 0 ? '+' : ''}${money(r.pnl)}</span>`;
      } else {
        pnlCell = '<span class="pnl-pending">pending</span>';
      }
    }
    const detail = expanded
      ? `<div class="feed-detail">reason: ${r.reason || '--'}\nshares: ${r.fill_shares != null ? r.fill_shares : '--'} · notional: ${r.fill_notional != null ? money(r.fill_notional) : '--'} · btc: ${r.btc_price != null ? nf2(r.btc_price) : '--'} · ref/open: ${r.reference_price != null ? nf2(r.reference_price) : '--'} · outcome: ${r.resolved ? (r.won ? 'WON' : 'LOST') : 'pending candle close'}</div>`
      : '';
    return `<div class="feed-row ${isNew ? 'new' : ''}" data-ts="${r.ts || ''}">
      <span>${(r.ts || '').slice(11, 19)}</span>
      <span class="tag ${tag}">${act.replace('BUY_', '')}</span>
      <span>${r.edge != null ? cents(r.edge) : '--'}</span>
      <span>${r.btc_price != null ? nf2(r.btc_price) : '--'}</span>
      <span class="st ${st}">${r.execution_status || '--'}</span>
      ${pnlCell}
      ${detail}
    </div>`;
  }).join('');
  feed.innerHTML = html || '<div class="feed-row"><span>No decisions match…</span></div>';
  if (rows) state.lastFeedKey = topKey;
}

// --- main render ---
function render(snapshot, pushHist = true) {
  state.latest = snapshot;
  if (pushHist) {
    state.btcHistory.push({ btc: Number(snapshot.btc_tick.price), ref: Number(snapshot.risk_state.reference_price) });
    if (state.btcHistory.length > state.maxHistory) state.btcHistory.shift();
  }
  renderTicker(snapshot);
  syncCountdown(snapshot);
  tickCountdown();
  renderHead(snapshot);
  renderOutcomes(snapshot);
  renderDecision(snapshot);
  renderRisk(snapshot);
  renderBook('upBook', snapshot.up_book);
  renderBook('downBook', snapshot.down_book);
  setText('upSpread', `spread ${cents(snapshot.up_book.spread)}`);
  setText('downSpread', `spread ${cents(snapshot.down_book.spread)}`);
  drawBtcChart();
}

// --- refresh loops ---
async function refresh(force = false) {
  if (state.paused && !force) return;
  try {
    render(await loadSnapshot());
    setConn(true);
  } catch (e) { setConn(false); console.error(e); }
}
async function refreshPerf() {
  if (state.paused) return;
  try { renderPerformance(await loadPerformance()); } catch (e) { console.error(e); }
}

function setConn(ok) {
  const c = document.getElementById('conn');
  c.className = 'conn' + (ok ? '' : ' off');
  setText('connText', ok ? 'LIVE' : 'OFFLINE');
}

// --- interactions ---
function selectOutcome(o) {
  state.selectedOutcome = o;
  document.getElementById('selectUp').classList.toggle('selected', o === 'UP');
  document.getElementById('selectDown').classList.toggle('selected', o === 'DOWN');
}
document.getElementById('selectUp').addEventListener('click', () => selectOutcome('UP'));
document.getElementById('selectDown').addEventListener('click', () => selectOutcome('DOWN'));
document.getElementById('pauseButton').addEventListener('click', (e) => {
  state.paused = !state.paused;
  e.target.textContent = state.paused ? 'Resume' : 'Pause';
});
document.getElementById('refreshButton').addEventListener('click', () => { refresh(true); refreshPerf(); });
document.querySelectorAll('.tab').forEach((t) => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach((x) => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById(t.dataset.tab).classList.add('active');
  });
});
// feed filters + expandable rows
document.querySelectorAll('.fbtn').forEach((b) => {
  b.addEventListener('click', () => {
    document.querySelectorAll('.fbtn').forEach((x) => x.classList.remove('active'));
    b.classList.add('active');
    state.feedFilter = b.dataset.filter;
    renderFeed(null);
  });
});
document.getElementById('tradeFeed').addEventListener('click', (e) => {
  const row = e.target.closest('.feed-row');
  if (!row || !row.dataset.ts) return;
  state.expanded = state.expanded === row.dataset.ts ? null : row.dataset.ts;
  renderFeed(null);
});
window.addEventListener('resize', () => { if (state.latest) render(state.latest, false); });

// --- boot ---
refresh(true);
refreshPerf();
setInterval(() => refresh(false), 900);
setInterval(() => refreshPerf(), 2500);
setInterval(tickCountdown, 250);
setInterval(tickActivity, 1000);
