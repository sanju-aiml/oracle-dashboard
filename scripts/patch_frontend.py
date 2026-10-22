with open("static/index.html", "r", encoding="utf-8") as f:
    html = f.read()

finllm_html_card = '''    <!-- FINLLM QUANT MODEL & NEURAL ENGINE CARD -->
    <div class="card" style="margin: 20px 0; border: 1px solid var(--gold); background: linear-gradient(135deg, rgba(212,175,55,0.06), rgba(16,185,129,0.04));">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px;">
        <div>
          <h3 style="margin:0; font-size:18px; color:var(--ink);">🧠 FinLLM Quant Signal &amp; DeepLOB Neural Engine</h3>
          <p style="font-size:12px; color:var(--mute); margin:3px 0 0 0;">
            Calibrated 5-day directional probabilities from trained HistGradientBoosting &amp; DeepLOB (PyTorch Conv+LSTM) models.
          </p>
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          <span class="tag actual" style="font-size:11px;" id="finllm-status-badge">Trained Model: Ready</span>
          <span class="tag" style="background:#e0f2fe; color:#0369a1; font-size:11px;" id="finllm-hitrate-badge">Out-of-Sample Hit Rate: 51.5%</span>
        </div>
      </div>

      <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:14px;">
        <!-- Quant Signal for Active Symbol -->
        <div style="background:#fff; border:1px solid var(--border); border-radius:8px; padding:14px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <b style="font-size:14px; color:var(--ink);" id="finllm-target-sym">AMZN Quant Signal</b>
            <span id="finllm-view-badge" class="tag" style="font-weight:700; font-size:12px; padding:4px 8px; background:#dcfce7; color:#15803d;">BULLISH</span>
          </div>
          <div style="margin:10px 0 6px 0;">
            <div style="display:flex; justify-content:space-between; font-size:12px; font-weight:600; margin-bottom:4px;">
              <span style="color:#15803d;" id="finllm-pup-label">P(Up): 38.2%</span>
              <span style="color:#64748b;" id="finllm-pflat-label">P(Flat): 44.3%</span>
              <span style="color:#b91c1c;" id="finllm-pdown-label">P(Down): 17.5%</span>
            </div>
            <!-- Probabilities Bar -->
            <div style="width:100%; height:10px; background:#e2e8f0; border-radius:5px; overflow:hidden; display:flex;">
              <div id="finllm-bar-up" style="width:38%; height:100%; background:#10b981;"></div>
              <div id="finllm-bar-flat" style="width:44%; height:100%; background:#94a3b8;"></div>
              <div id="finllm-bar-down" style="width:18%; height:100%; background:#ef4444;"></div>
            </div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:11.5px; color:var(--mute); margin-top:8px;">
            <span>Recommended Action: <b id="finllm-action" style="color:var(--ink);">BUY (Edge +20.7%)</b></span>
            <span>Confidence: <b id="finllm-conf">38.2%</b></span>
          </div>
          <div style="margin-top:8px; padding-top:8px; border-top:1px dashed var(--border); display:flex; justify-content:space-between; font-size:11px; color:var(--mute);">
            <span>RSI(14): <b id="finllm-rsi">57.4</b></span>
            <span>ATR: <b id="finllm-atr">2.4%</b></span>
            <span>21d Mom: <b id="finllm-mom">+0.0%</b></span>
          </div>
        </div>

        <!-- DeepLOB Microstructure -->
        <div style="background:#fff; border:1px solid var(--border); border-radius:8px; padding:14px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <b style="font-size:14px; color:var(--ink);">DeepLOB Microstructure</b>
            <span class="tag" style="background:#fef3c7; color:#92400e; font-size:11px;">PyTorch 2.x</span>
          </div>
          <p style="font-size:12px; color:var(--mute); margin:6px 0 10px 0;">
            Convolutional + Inception + LSTM neural network trained on tick order dynamics (arXiv:1808.03668).
          </p>
          <div style="font-size:12.5px; margin-bottom:6px;">
            Neural Momentum View: <b id="deeplob-view" style="color:var(--emerald);">NEUTRAL / BALANCED</b>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:11.5px; color:var(--mute);">
            <span>Down: <b id="deeplob-down">33.3%</b></span>
            <span>Flat: <b id="deeplob-flat">33.4%</b></span>
            <span>Up: <b id="deeplob-up">33.3%</b></span>
          </div>
          <div style="margin-top:10px; font-size:11px; color:var(--mute); background:#f8fafc; padding:6px 8px; border-radius:4px;">
            Weights: <code style="font-size:10px;">uploaded_model/finllm/runs/deeplob.pt</code>
          </div>
        </div>

        <!-- FinLLM CA Compliance & Intelligence -->
        <div style="background:#fff; border:1px solid var(--border); border-radius:8px; padding:14px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <b style="font-size:14px; color:var(--ink);">CA Banking &amp; Safety Guards</b>
            <span class="tag actual" style="font-size:11px;">Verified Math</span>
          </div>
          <ul style="font-size:11.5px; color:var(--ink-light); margin:8px 0 0 16px; padding:0; line-height:1.6;">
            <li>Zero-Hallucination: Prices &amp; math strictly routed to tools</li>
            <li>Anti-Fraud Guard: Prohibits 'guaranteed returns' claims</li>
            <li>Human Approval Gate: Execution blocked without explicit confirm</li>
            <li>Exact Banking Slabs: GST, EMI, FY25-26 New Tax Regime</li>
          </ul>
          <div style="margin-top:10px;">
            <button class="btn" style="padding:4px 10px; font-size:11.5px; width:100%;" onclick="quickChat('Check FinLLM model status and tell me about Amazon')">💬 Ask FinLLM in Chatbot</button>
          </div>
        </div>
      </div>
    </div>

'''

target_html = '    <!-- GLOBAL TICKERS: SENSEX, NIFTY, FOREX, CRYPTO & COMMODITIES -->'
if "FinLLM Quant Signal &amp; DeepLOB Neural Engine" not in html:
    if target_html in html:
        html = html.replace(target_html, finllm_html_card + target_html)
        print("[*] Injected FinLLM HTML Card")

# Inject JavaScript function and call into selectTicker()
finllm_js = '''
async function loadFinLLMSignal(sym, reqId) {
  try {
    const res = await fetch('/api/finllm/signal?symbol=' + encodeURIComponent(sym)).then(r => r.json());
    if (reqId && reqId !== currentTickerRequestId) return;
    if (res && res.status === 'ok') {
      const p = res.probabilities || { p_up: 0.33, p_flat: 0.34, p_down: 0.33 };
      if ($('#finllm-target-sym')) $('#finllm-target-sym').textContent = sym + ' Quant Signal';
      if ($('#finllm-view-badge')) {
        const v = (res.view || 'neutral').toUpperCase();
        $('#finllm-view-badge').textContent = v;
        if (v === 'BULLISH') {
          $('#finllm-view-badge').style.background = '#dcfce7';
          $('#finllm-view-badge').style.color = '#15803d';
        } else if (v === 'BEARISH') {
          $('#finllm-view-badge').style.background = '#fee2e2';
          $('#finllm-view-badge').style.color = '#b91c1c';
        } else {
          $('#finllm-view-badge').style.background = '#fef3c7';
          $('#finllm-view-badge').style.color = '#92400e';
        }
      }
      if ($('#finllm-pup-label')) $('#finllm-pup-label').textContent = 'P(Up): ' + (p.p_up * 100).toFixed(1) + '%';
      if ($('#finllm-pflat-label')) $('#finllm-pflat-label').textContent = 'P(Flat): ' + (p.p_flat * 100).toFixed(1) + '%';
      if ($('#finllm-pdown-label')) $('#finllm-pdown-label').textContent = 'P(Down): ' + (p.p_down * 100).toFixed(1) + '%';

      if ($('#finllm-bar-up')) $('#finllm-bar-up').style.width = (p.p_up * 100) + '%';
      if ($('#finllm-bar-flat')) $('#finllm-bar-flat').style.width = (p.p_flat * 100) + '%';
      if ($('#finllm-bar-down')) $('#finllm-bar-down').style.width = (p.p_down * 100) + '%';

      if ($('#finllm-action')) {
        const act = (res.action || 'abstain').toUpperCase();
        const edgeStr = (res.edge !== undefined) ? ` (Edge ${(res.edge * 100 >= 0 ? '+' : '')}${(res.edge * 100).toFixed(1)}%)` : '';
        $('#finllm-action').textContent = act + edgeStr;
        $('#finllm-action').style.color = act === 'BUY' ? '#15803d' : (act === 'SELL' ? '#b91c1c' : '#475569');
      }
      if ($('#finllm-conf')) $('#finllm-conf').textContent = ((res.confidence || 0) * 100).toFixed(1) + '%';

      const ind = res.indicators || {};
      if ($('#finllm-rsi')) $('#finllm-rsi').textContent = ind.rsi_14 !== undefined ? ind.rsi_14 : '-';
      if ($('#finllm-atr')) $('#finllm-atr').textContent = ind.atr_pct !== undefined ? ind.atr_pct + '%' : '-';
      if ($('#finllm-mom')) $('#finllm-mom').textContent = ind.momentum_21d || '-';
    }
  } catch(e) {}

  try {
    const dRes = await fetch('/api/finllm/deeplob?symbol=' + encodeURIComponent(sym)).then(r => r.json());
    if (reqId && reqId !== currentTickerRequestId) return;
    if (dRes && dRes.status === 'ok') {
      const dp = dRes.probabilities || {};
      if ($('#deeplob-view')) {
        const dv = (dRes.view || 'neutral').toUpperCase();
        $('#deeplob-view').textContent = dv;
        $('#deeplob-view').style.color = dv === 'BULLISH' ? '#15803d' : (dv === 'BEARISH' ? '#b91c1c' : '#92400e');
      }
      if ($('#deeplob-down')) $('#deeplob-down').textContent = ((dp.down || 0) * 100).toFixed(1) + '%';
      if ($('#deeplob-flat')) $('#deeplob-flat').textContent = ((dp.flat || 0) * 100).toFixed(1) + '%';
      if ($('#deeplob-up')) $('#deeplob-up').textContent = ((dp.up || 0) * 100).toFixed(1) + '%';
    }
  } catch(e) {}
}
'''

if "function loadFinLLMSignal" not in html:
    call_target = "loadCompanyDeepDive(sym, reqId);"
    if call_target in html:
        html = html.replace(call_target, call_target + "\n  loadFinLLMSignal(sym, reqId);")
        print("[*] Injected loadFinLLMSignal into selectTicker()")

    # Insert function definition before </script>
    script_end = "</script>"
    idx = html.rfind(script_end)
    if idx != -1:
        html = html[:idx] + finllm_js + "\n" + html[idx:]
        print("[*] Injected loadFinLLMSignal function definition")

with open("static/index.html", "w", encoding="utf-8") as f:
    f.write(html)
print("[*] Saved updated static/index.html")
