import os

html_path = r"C:\Users\BOTTA THARUN\Videos\oracle\oracle\static\index.html"
with open(html_path, "r", encoding="utf-8") as f:
    html = f.read()

# Normalize
html = html.replace("\r\n", "\n")

# 1. Update fetchPaperTrading
old_fetch_pt = """    async function fetchPaperTrading() {
      const out = $('#pt-out');
      try {
        const res = await fetch('/api/market/paper-trade', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'summary' })
        });
        if (!res.ok) {
          if (out) out.textContent = 'Paper trading unavailable';
          return;
        }
        const data = await res.json();
        if (out) out.textContent = JSON.stringify(data, null, 2);
      } catch (e) {
        if (out) out.textContent = 'Paper trading unavailable';
      }
    }"""

new_fetch_pt = """    async function fetchPaperTrading() {
      const out = $('#pt-out');
      try {
        const res = await fetch('/api/market/paper-trade', { method: 'GET' });
        if (!res.ok) {
          if (out) out.textContent = 'Paper trading unavailable';
          return;
        }
        const data = await res.json();
        // Map fields: equity, cash, return_pct, open_positions, recent_closed, win_rate, halted
        const cashEl = $('#alpaca-cash');
        if (cashEl && data.cash !== undefined) {
          cashEl.textContent = '$' + Number(data.cash).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }
        const eqEl = $('#alpaca-equity');
        if (eqEl && data.equity !== undefined) {
          eqEl.textContent = '$' + Number(data.equity).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
        }
        const bpEl = $('#alpaca-bp');
        if (bpEl && data.return_pct !== undefined) {
          bpEl.textContent = (data.return_pct >= 0 ? '+' : '') + Number(data.return_pct).toFixed(2) + '%';
        }
        const badgeEl = $('#alpaca-status-badge');
        if (badgeEl) {
          if (data.halted) {
            badgeEl.textContent = 'HALTED: ' + (data.halt_reason || 'Kill switch');
            badgeEl.className = 'tag synthetic';
          } else {
            badgeEl.textContent = 'Virtual Sandbox Active';
            badgeEl.className = 'tag actual';
          }
        }
        const posCont = $('#alpaca-positions-container');
        if (posCont && Array.isArray(data.open_positions)) {
          if (data.open_positions.length === 0) {
            posCont.innerHTML = '<span style="color:var(--mute); font-size:12.5px;">No open positions</span>';
          } else {
            posCont.innerHTML = data.open_positions.map(p => `
              <div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border); font-size:12.5px;">
                <b>${esc(p.symbol)} (${esc(p.side)})</b>
                <span>${Number(p.qty).toFixed(2)} @ $${Number(p.entry_price).toFixed(2)}</span>
                <span style="color:${(p.unrealized||0)>=0 ? 'var(--emerald-dark)' : '#b91c1c'}; font-weight:700;">
                  ${(p.unrealized||0)>=0 ? '+' : ''}$${Number(p.unrealized||0).toFixed(2)}
                </span>
              </div>
            `).join('');
          }
        }
        if (out) out.textContent = JSON.stringify(data, null, 2);
      } catch (e) {
        if (out) out.textContent = 'Paper trading unavailable';
      }
    }"""

if old_fetch_pt in html:
    html = html.replace(old_fetch_pt, new_fetch_pt, 1)

# 2. Update sendChatMessage to route to POST /api/ask
old_send_chat = """    async function sendChatMessage() {
      const inp = $('#chat-input');
      const msg = inp.value.trim();
      if (!msg) return;
      inp.value = '';

      const log = $('#chat-log');
      const uMsg = document.createElement('div');
      uMsg.className = 'msg-user';
      uMsg.textContent = msg;
      log.appendChild(uMsg);

      _chatHistory.push({role: 'user', content: msg});

      if (typeof askBot === 'function') {
        await askBot(msg, _chatHistory, function(ev) {
          renderEvent(log, ev);
          if (ev.type === 'final' && ev.text) {
            _chatHistory.push({role: 'assistant', content: ev.text});
          }
          log.scrollTop = log.scrollHeight;
        });
      }
    }"""

new_send_chat = """    async function sendChatMessage() {
      const inp = $('#chat-input');
      const msg = inp.value.trim();
      if (!msg) return;
      inp.value = '';

      const log = $('#chat-log');
      const uMsg = document.createElement('div');
      uMsg.className = 'msg-user';
      uMsg.textContent = msg;
      log.appendChild(uMsg);

      _chatHistory.push({role: 'user', content: msg});

      try {
        const res = await fetch('/api/ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: msg })
        });
        if (res.ok) {
          const data = await res.json();
          renderEvent(log, {
            type: 'final',
            text: data.answer,
            mode: 'ai',
            verified: true,
            warnings: [],
            needs_approval: []
          });
          _chatHistory.push({role: 'assistant', content: data.answer});
          log.scrollTop = log.scrollHeight;
          return;
        }
      } catch (e) {}

      if (typeof askBot === 'function') {
        await askBot(msg, _chatHistory, function(ev) {
          renderEvent(log, ev);
          if (ev.type === 'final' && ev.text) {
            _chatHistory.push({role: 'assistant', content: ev.text});
          }
          log.scrollTop = log.scrollHeight;
        });
      }
    }"""

if old_send_chat in html:
    html = html.replace(old_send_chat, new_send_chat, 1)

# 3. Update submitAuth for Terms checkbox acceptance
old_submit_auth = """    async function submitAuth(type) {
      const email = $('#auth-email').value.trim();
      const pwd = $('#auth-pwd').value.trim();
      try {
        const res = await api('auth/' + type, { email, password: pwd });
        localStorage.setItem('oracle_token', res.token);
        $('#role-badge').textContent = 'Role: ' + res.role;
        $('#auth-out').textContent = `Signed in successfully as ${res.role}!`;
        loadData();
      } catch (e) {
        $('#auth-out').textContent = e.message;
      }
    }"""

new_submit_auth = """    async function submitAuth(type) {
      const email = $('#auth-email').value.trim();
      const pwd = $('#auth-pwd').value.trim();
      const termsBox = $('#auth-terms-checkbox');

      if (type === 'register') {
        if (termsBox && !termsBox.checked) {
          alert('Please accept the Terms of Service (v1.0) before creating a workspace.');
          return;
        }
        localStorage.setItem('oracle_terms_accepted', JSON.stringify({
          version: '1.0',
          accepted_at: new Date().toISOString()
        }));
      }

      try {
        const res = await api('auth/' + type, { email, password: pwd });
        localStorage.setItem('oracle_token', res.token);
        $('#role-badge').textContent = 'Role: ' + res.role;
        $('#auth-out').textContent = `Signed in successfully as ${res.role}!`;
        loadData();
      } catch (e) {
        $('#auth-out').textContent = e.message;
      }
    }"""

if old_submit_auth in html:
    html = html.replace(old_submit_auth, new_submit_auth, 1)

# 4. Inject all new functionality right before </script>
new_js_code = """
// ========================================================
// ORACLE AI EXTENDED ENGINE & LIVE STREAMING INTEGRATION
// ========================================================

function getUserId() {
  let uid = localStorage.getItem('oracle_user_id');
  if (!uid) {
    uid = 'user_' + Math.random().toString(36).substring(2, 10) + Math.random().toString(36).substring(2, 10);
    localStorage.setItem('oracle_user_id', uid);
  }
  return uid;
}

let currentImageToken = null;

function selectDuration(dur, btn) {
  const durInp = $('#play-duration');
  if (durInp) durInp.value = dur;
  document.querySelectorAll('.dur-btn').forEach(b => {
    b.className = 'btn btn-outline dur-btn';
  });
  if (btn) btn.className = 'btn btn-gold dur-btn';
}

async function uploadChartImage() {
  const fileInp = $('#chart-file-input');
  const consentCb = $('#chart-consent-checkbox');
  const statusBox = $('#chart-upload-status');
  if (!fileInp || !fileInp.files || fileInp.files.length === 0) {
    if (statusBox) statusBox.textContent = 'Please choose a chart screenshot image first.';
    return;
  }
  const file = fileInp.files[0];
  const formData = new FormData();
  formData.append('file', file);
  formData.append('consent', consentCb && consentCb.checked ? 'true' : 'false');
  if (statusBox) statusBox.textContent = 'Scanning candlestick wicks and bodies...';

  try {
    const res = await fetch('/api/chart/analyze', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      if (statusBox) statusBox.textContent = 'Analysis Failed: ' + (data.reason || 'Could not find candle bodies');
      return;
    }
    currentImageToken = data.image_token;
    if (statusBox) {
      statusBox.innerHTML = `
        <div style="color:var(--emerald-dark); font-weight:600;">✅ ${esc(data.message)}</div>
        <div style="font-size:11.5px; color:var(--mute); margin-top:4px;">
          P(Up): ${(data.p_up * 100).toFixed(0)}% | P(Down): ${(data.p_down * 100).toFixed(0)}% | Token: <code>${esc(data.image_token)}</code>
        </div>
      `;
    }
  } catch (e) {
    if (statusBox) statusBox.textContent = 'Chart upload error: ' + e.message;
  }
}

async function submitPlayCall(direction) {
  const symEl = $('#play-symbol');
  const durEl = $('#play-duration');
  const statusBox = $('#play-call-status');
  const sym = symEl ? symEl.value : 'AMZN';
  const dur = durEl ? durEl.value : '1h';
  const uid = getUserId();

  if (statusBox) statusBox.textContent = `Locking entry price for ${sym} (${direction.toUpperCase()})...`;

  try {
    const res = await fetch('/api/play/call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: uid,
        symbol: sym,
        call: direction,
        duration: dur,
        image_token: currentImageToken || null
      })
    });
    const data = await res.json();
    if (!res.ok) {
      if (statusBox) statusBox.textContent = 'Error: ' + (data.detail || 'Could not record call');
      return;
    }
    const resolvesDate = new Date(data.resolves_at * 1000).toLocaleTimeString();
    if (statusBox) {
      statusBox.innerHTML = `
        <span style="color:var(--emerald); font-weight:700;">✅ Call Locked (#${data.id})!</span>
        ${esc(data.symbol)} <b>${esc(data.call).toUpperCase()}</b> locked @ <b>$${Number(data.entry_price).toFixed(2)}</b> (${esc(data.price_source)}). Resolves at ${resolvesDate}.
      `;
    }
    loadPlayHistory();
  } catch (e) {
    if (statusBox) statusBox.textContent = 'Call error: ' + e.message;
  }
}

async function loadPlayHistory() {
  const cont = $('#play-history-table-container');
  const uid = getUserId();
  try {
    const res = await fetch('/api/play/history?user_id=' + encodeURIComponent(uid));
    const data = await res.json();
    if (data.stats) {
      if ($('#play-stat-total')) $('#play-stat-total').textContent = data.stats.total || 0;
      if ($('#play-stat-wins')) $('#play-stat-wins').textContent = data.stats.wins || 0;
      const wr = data.stats.win_rate !== null && data.stats.win_rate !== undefined ? (data.stats.win_rate * 100).toFixed(1) + '%' : '-';
      if ($('#play-stat-winrate')) $('#play-stat-winrate').textContent = wr;
    }
    if (cont) {
      if (!data.history || data.history.length === 0) {
        cont.innerHTML = '<span style="color:var(--mute); font-size:12.5px;">No prediction calls recorded yet. Make your first call above!</span>';
        return;
      }
      let rows = data.history.map(h => {
        const isResolved = h.status === 'resolved';
        const isWin = h.result === 'win';
        const pnl = h.pnl_pct !== null && h.pnl_pct !== undefined ? (h.pnl_pct >= 0 ? '+' : '') + Number(h.pnl_pct).toFixed(2) + '%' : '-';
        const resBadge = isResolved
          ? `<span class="tag ${isWin ? 'actual' : 'synthetic'}">${esc(h.result).toUpperCase()} (${pnl})</span>`
          : '<span class="tag calculated">ACTIVE</span>';
        const closePx = h.close_price !== null && h.close_price !== undefined ? '$' + Number(h.close_price).toFixed(2) : 'Pending';
        return `
          <tr>
            <td><b>${esc(h.symbol)}</b></td>
            <td><b style="color:${h.call === 'up' ? 'var(--emerald)' : '#b91c1c'}">${esc(h.call).toUpperCase()}</b></td>
            <td>$${Number(h.entry_price).toFixed(2)}</td>
            <td>${closePx}</td>
            <td>${esc(h.duration || '-')}</td>
            <td>${resBadge}</td>
          </tr>
        `;
      }).join('');
      cont.innerHTML = `<table><thead><tr><th>Asset</th><th>Call</th><th>Entry</th><th>Exit</th><th>Duration</th><th>Outcome</th></tr></thead><tbody>${rows}</tbody></table>`;
    }
  } catch (e) {
    if (cont) cont.innerHTML = '<span style="color:var(--mute); font-size:12px;">History unavailable.</span>';
  }
}

async function loadAlertKinds() {
  try {
    const res = await fetch('/api/alerts/kinds');
    const kinds = await res.json();
    const sel = $('#alert-rule-kind');
    if (sel && kinds) {
      sel.innerHTML = Object.entries(kinds).map(([k, v]) => `
        <option value="${k}">${esc(v.name || k)} (${esc(v.unit || '')})</option>
      `).join('');
    }
  } catch(e) {}
}

async function submitAlertRule() {
  const symEl = $('#alert-rule-symbol');
  const kindEl = $('#alert-rule-kind');
  const threshEl = $('#alert-rule-threshold');
  const cdEl = $('#alert-rule-cooldown');
  const statusBox = $('#alert-rule-status');
  const sym = symEl ? symEl.value.toUpperCase().trim() : '';
  const kind = kindEl ? kindEl.value : 'above';
  const thresh = threshEl ? parseFloat(threshEl.value) : NaN;
  const cd = cdEl ? parseFloat(cdEl.value || '4') : 4;
  const uid = getUserId();

  if (!sym || isNaN(thresh)) {
    if (statusBox) statusBox.textContent = 'Please enter a valid symbol and threshold value.';
    return;
  }
  try {
    const res = await fetch('/api/alerts/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: uid,
        symbol: sym,
        kind: kind,
        threshold: thresh,
        cooldown_hours: cd
      })
    });
    const data = await res.json();
    if (!res.ok) {
      if (statusBox) statusBox.textContent = 'Error: ' + (data.detail || 'Could not add rule');
      return;
    }
    if (statusBox) statusBox.textContent = `Alert rule #${data.id} active for ${sym} ${kind} @ ${thresh}.`;
    if (threshEl) threshEl.value = '';
    loadAlertRules();
  } catch(e) {
    if (statusBox) statusBox.textContent = 'Alert rule error: ' + e.message;
  }
}

async function loadAlertRules() {
  const cont = $('#alert-rules-list-container');
  const uid = getUserId();
  try {
    const res = await fetch('/api/alerts/rules?user_id=' + encodeURIComponent(uid));
    const rules = await res.json();
    if (cont) {
      if (!rules || rules.length === 0) {
        cont.innerHTML = '<span style="color:var(--mute); font-size:12.5px;">No active price rules configured.</span>';
        return;
      }
      let rows = rules.map(r => `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid var(--border); font-size:12.5px;">
          <div>
            <b>${esc(r.symbol)}</b> · <code>${esc(r.kind)}</code> @ <b>${r.threshold}</b>
          </div>
          <button class="btn btn-outline" style="padding:2px 8px; font-size:11px;" onclick="deleteAlertRule(${r.id})">Delete</button>
        </div>
      `).join('');
      cont.innerHTML = rows;
    }
  } catch(e) {
    if (cont) cont.innerHTML = '<span style="color:var(--mute); font-size:12px;">Rules unavailable.</span>';
  }
}

async function deleteAlertRule(ruleId) {
  const uid = getUserId();
  try {
    await fetch(`/api/alerts/rules/${ruleId}?user_id=${encodeURIComponent(uid)}`, { method: 'DELETE' });
    loadAlertRules();
  } catch(e) {}
}

async function saveAlertChannel() {
  const topEl = $('#alert-ntfy-topic');
  const statusBox = $('#alert-channel-status');
  const topic = topEl ? topEl.value.trim() : '';
  const uid = getUserId();
  if (!topic) {
    if (statusBox) statusBox.textContent = 'Please enter an ntfy topic name (8-64 alphanumeric chars).';
    return;
  }
  try {
    const res = await fetch('/api/alerts/channel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: uid, ntfy_topic: topic })
    });
    const data = await res.json();
    if (!res.ok) {
      if (statusBox) statusBox.textContent = 'Error: ' + (data.detail || 'Could not save topic');
      return;
    }
    localStorage.setItem('oracle_ntfy_topic', topic);
    if (statusBox) statusBox.textContent = `Topic '${topic}' saved! Subscribe in the ntfy app at https://ntfy.sh/${topic}`;
  } catch(e) {
    if (statusBox) statusBox.textContent = 'Topic save error: ' + e.message;
  }
}

async function sendTestAlert() {
  const statusBox = $('#alert-channel-status');
  const uid = getUserId();
  if (statusBox) statusBox.textContent = 'Sending test notification...';
  try {
    const res = await fetch('/api/alerts/test?user_id=' + encodeURIComponent(uid), { method: 'POST' });
    const data = await res.json();
    if (data.delivered) {
      if (statusBox) statusBox.innerHTML = '<span style="color:var(--emerald-dark); font-weight:700;">✅ Notification delivered! Check your phone.</span>';
    } else {
      if (statusBox) statusBox.innerHTML = '<span style="color:var(--danger);">⚠️ Delivery failed. Configure an ntfy topic first.</span>';
    }
    loadAlertLog();
  } catch(e) {
    if (statusBox) statusBox.textContent = 'Test failed: ' + e.message;
  }
}

async function saveHolding() {
  const symEl = $('#hold-sym');
  const qtyEl = $('#hold-qty');
  const avgEl = $('#hold-price');
  const stopEl = $('#hold-stop');
  const tgtEl = $('#hold-target');
  const sym = symEl ? symEl.value.toUpperCase().trim() : '';
  const qty = qtyEl ? parseFloat(qtyEl.value) : NaN;
  const avg = avgEl ? parseFloat(avgEl.value) : NaN;
  const stop = stopEl ? parseFloat(stopEl.value || '8.0') : 8.0;
  const tgt = tgtEl ? parseFloat(tgtEl.value || '15.0') : 15.0;
  const uid = getUserId();

  if (!sym || isNaN(qty) || isNaN(avg)) {
    alert('Please enter symbol, quantity, and average purchase price.');
    return;
  }
  try {
    const res = await fetch('/api/holdings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: uid, symbol: sym, qty: qty, avg_price: avg, stop_pct: stop, target_pct: tgt })
    });
    if (res.ok) {
      loadHoldings();
    }
  } catch(e) {}
}

async function loadHoldings() {
  const cont = $('#holdings-list-container');
  const uid = getUserId();
  try {
    const res = await fetch('/api/holdings?user_id=' + encodeURIComponent(uid));
    const hList = await res.json();
    if (cont) {
      if (!hList || hList.length === 0) {
        cont.innerHTML = '<span style="color:var(--mute); font-size:12px;">No tracked holdings yet.</span>';
        return;
      }
      let rows = hList.map(h => `
        <div style="display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid var(--border); font-size:12px;">
          <div><b>${esc(h.symbol)}</b> · ${h.qty} shares @ $${Number(h.avg_price).toFixed(2)}</div>
          <div>Stop: <b>${h.stop_pct}%</b> | Target: <b>${h.target_pct}%</b></div>
        </div>
      `).join('');
      cont.innerHTML = rows;
    }
  } catch(e) {}
}

async function loadAlertLog() {
  const cont = $('#alert-log-container');
  const uid = getUserId();
  try {
    const res = await fetch('/api/alerts/log?user_id=' + encodeURIComponent(uid));
    const logs = await res.json();
    if (cont) {
      if (!logs || logs.length === 0) {
        cont.innerHTML = '<span style="color:var(--mute); font-size:12.5px;">No triggered alert records.</span>';
        return;
      }
      let rows = logs.map(l => {
        const timeStr = new Date(l.ts * 1000).toLocaleString();
        return `
          <div style="padding:6px 0; border-bottom:1px solid var(--border); font-size:12px;">
            <div style="display:flex; justify-content:space-between;">
              <b>${esc(l.title || l.kind)} (${esc(l.symbol)})</b>
              <small style="color:var(--mute)">${timeStr}</small>
            </div>
            <div style="color:var(--ink-light); margin-top:2px;">${esc(l.body)}</div>
          </div>
        `;
      }).join('');
      cont.innerHTML = rows;
    }
  } catch(e) {}
}

async function loadAllIpos() {
  const cont = $('#ipos-full-container');
  try {
    const res = await fetch('/api/ipos');
    const ipos = await res.json();
    if (cont) {
      if (!ipos || ipos.length === 0) {
        cont.innerHTML = '<span style="color:var(--mute); font-size:12.5px;">No IPOs in current pipeline.</span>';
        return;
      }
      let rows = ipos.map(i => `
        <div style="padding:6px 0; border-bottom:1px solid var(--border); font-size:12px;">
          <div style="display:flex; justify-content:space-between;">
            <b>${esc(i.name)}</b>
            <span class="tag actual" style="font-size:10px;">${esc(i.open_date)} to ${esc(i.close_date)}</span>
          </div>
          <div style="color:var(--mute); margin-top:2px;">Band: ${esc(i.price_band || '-')} | Lot: ${esc(i.lot_size || '-')}</div>
        </div>
      `).join('');
      cont.innerHTML = rows;
    }
  } catch(e) {}
}

// ========================================================
// LIVE SSE PRICE CARD STREAMS (Google/Groww Style)
// ========================================================
const _cardEventSources = new Map();

function setupCardLiveStream(cardSelector, symbol, priceSelector, badgeSelector, metaSelector, isINR=false) {
  const card = document.querySelector(cardSelector);
  if (!card) return;

  function connect() {
    if (_cardEventSources.has(symbol)) return;
    const es = new EventSource('/api/stream/' + encodeURIComponent(symbol) + '?interval=5');
    _cardEventSources.set(symbol, es);

    es.onmessage = (evt) => {
      try {
        const q = JSON.parse(evt.data);
        if (!q) return;

        const pEl = document.querySelector(priceSelector);
        if (pEl && q.price !== null && q.price !== undefined) {
          const prefix = isINR ? '₹' : '$';
          pEl.textContent = prefix + Number(q.price).toLocaleString(isINR ? 'en-IN' : 'en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: q.price < 1 ? 4 : 2
          });
        }

        const bEl = document.querySelector(badgeSelector);
        if (bEl) {
          if (q.market === 'closed') {
            bEl.textContent = 'Market closed: last traded price';
            bEl.className = 'tag';
            bEl.style.background = '#f1f3f4';
            bEl.style.color = '#5f6368';
          } else if (q.status === 'fresh') {
            bEl.textContent = 'LIVE';
            bEl.className = 'tag actual';
          } else if (q.status === 'backup') {
            bEl.textContent = 'BACKUP';
            bEl.className = 'tag calculated';
          } else if (q.status === 'stale') {
            bEl.textContent = 'LAST CLOSE';
            bEl.className = 'tag';
          }
        }

        const mEl = metaSelector ? document.querySelector(metaSelector) : null;
        if (mEl) {
          const ago = q.age_sec != null ? (q.age_sec < 60 ? `${q.age_sec}s ago` : `${Math.floor(q.age_sec/60)}m ago`) : 'just now';
          const chg = q.change_pct != null ? ` (${q.change_pct >= 0 ? '+' : ''}${q.change_pct.toFixed(2)}%)` : '';
          mEl.textContent = `${q.source || 'Live'} · ${ago}${chg}`;
        }
      } catch (err) {}
    };

    es.onerror = () => {};
  }

  function disconnect() {
    const es = _cardEventSources.get(symbol);
    if (es) {
      es.close();
      _cardEventSources.delete(symbol);
    }
  }

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          connect();
        } else {
          disconnect();
        }
      });
    }, { threshold: 0.05 });
    observer.observe(card);
  } else {
    connect();
  }
}

function initAllPriceStreams() {
  // SENSEX, NIFTY, FOREX, BTC, ETH, NATGAS, OIL, GOLD, SILVER
  setupCardLiveStream('#sensex-price', 'SENSEX', '#sensex-price', '#sensex-badge', null, true);
  setupCardLiveStream('#nifty-price', 'NIFTY', '#nifty-price', '#nifty-badge', null, true);
  setupCardLiveStream('#forex-usd-inr', 'USDINR', '#forex-usd-inr', null, null, true);
  setupCardLiveStream('#btc-price', 'BTC', '#btc-price', null, null, false);
  setupCardLiveStream('#eth-price', 'ETH', '#eth-price', null, null, false);
  setupCardLiveStream('#natgas-price', 'NG', '#natgas-price', '#natgas-badge', null, false);
  setupCardLiveStream('#oil-price-display', 'WTI', '#oil-price-display', null, null, false);
  setupCardLiveStream('#gold-price-display', 'XAU', '#gold-price-display', null, null, false);
  setupCardLiveStream('#silver-price-display', 'XAG', '#silver-price-display', null, null, false);
}

// Bootstrap on DOM ready
window.addEventListener('DOMContentLoaded', () => {
  const savedTopic = localStorage.getItem('oracle_ntfy_topic');
  if (savedTopic && $('#alert-ntfy-topic')) {
    $('#alert-ntfy-topic').value = savedTopic;
  }
  loadPlayHistory();
  loadAlertKinds();
  loadAlertRules();
  loadHoldings();
  loadAlertLog();
  loadAllIpos();
  initAllPriceStreams();
});
"""

script_close = "</script>"
if script_close in html and "initAllPriceStreams" not in html:
    html = html.replace(script_close, new_js_code + "\n" + script_close, 1)

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html.replace("\n", "\r\n"))

print("Successfully injected all JavaScript functions and SSE streaming logic.")
