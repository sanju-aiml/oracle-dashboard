import re

html_path = r"C:\Users\BOTTA THARUN\Videos\oracle\oracle\static\index.html"
with open(html_path, "r", encoding="utf-8") as f:
    html = f.read()

# Normalize newlines
html = html.replace("\r\n", "\n")

# 1. Add nav buttons to sidebar
old_nav = """      <div class="nav-label">Finance &amp; Markets</div>
      <button class="nav-btn" data-target="calculators">🧮 Wealth &amp; Calculators</button>
      <button class="nav-btn" data-target="markets">📈 Markets, IPOs &amp; Paper</button>
      <button class="nav-btn" data-target="cricket">🏏 International Cricket</button>"""

new_nav = """      <div class="nav-label">Finance &amp; Markets</div>
      <button class="nav-btn" data-target="calculators">🧮 Wealth &amp; Calculators</button>
      <button class="nav-btn" data-target="markets">📈 Markets, IPOs &amp; Paper</button>
      <button class="nav-btn" data-target="prediction-game">🎮 UP / DOWN Prediction Game</button>
      <button class="nav-btn" data-target="alerts-screen">🔔 Market Radar &amp; Alerts</button>
      <button class="nav-btn" data-target="cricket">🏏 International Cricket</button>"""

if old_nav in html:
    html = html.replace(old_nav, new_nav, 1)

# 2. Add sections for prediction-game and alerts-screen
prediction_game_section = """
      <!-- UP / DOWN PREDICTION GAME & CHART ANALYSIS -->
      <section id="prediction-game" class="pane">
        <h2>🎮 UP / DOWN Market Prediction Game</h2>
        <p>Call the direction of any asset over your chosen duration (5m, 15m, 1h, 1d). Lock in the live entry price and see your validated track record.</p>

        <div class="grid-2" style="margin-top:16px;">
          <!-- Call Form Card -->
          <div class="card" style="border: 2px solid var(--gold-border);">
            <h3>🎯 Place Your Call</h3>
            <div style="margin-bottom:12px;">
              <label>Select Asset:
                <select id="play-symbol" style="width:100%; padding:8px; border-radius:6px; border:1px solid var(--border); font-weight:700;">
                  <option value="AMZN">Amazon (AMZN)</option>
                  <option value="AAPL">Apple (AAPL)</option>
                  <option value="NVDA">Nvidia (NVDA)</option>
                  <option value="TSLA">Tesla (TSLA)</option>
                  <option value="NIFTY">Nifty 50 (NIFTY)</option>
                  <option value="SENSEX">Sensex (SENSEX)</option>
                  <option value="RELIANCE">Reliance Industries (RELIANCE.NS)</option>
                  <option value="TCS">Tata Consultancy (TCS.NS)</option>
                  <option value="BTC">Bitcoin (BTC)</option>
                  <option value="ETH">Ethereum (ETH)</option>
                  <option value="XAU">Gold Spot (XAU)</option>
                  <option value="XAG">Silver Spot (XAG)</option>
                  <option value="WTI">Crude Oil (WTI)</option>
                  <option value="NG">Natural Gas (NG)</option>
                </select>
              </label>
            </div>

            <div style="margin-bottom:14px;">
              <label>Duration:
                <div style="display:flex; gap:8px; margin-top:4px;">
                  <button type="button" class="btn btn-outline dur-btn" data-dur="5m" onclick="selectDuration('5m', this)">5 Mins</button>
                  <button type="button" class="btn btn-outline dur-btn" data-dur="15m" onclick="selectDuration('15m', this)">15 Mins</button>
                  <button type="button" class="btn btn-gold dur-btn" data-dur="1h" onclick="selectDuration('1h', this)">1 Hour</button>
                  <button type="button" class="btn btn-outline dur-btn" data-dur="1d" onclick="selectDuration('1d', this)">1 Day</button>
                </div>
              </label>
              <input type="hidden" id="play-duration" value="1h">
            </div>

            <div style="display:flex; gap:12px; margin-top:16px;">
              <button class="btn" style="flex:1; background:var(--emerald); color:#fff; font-size:16px; font-weight:700; height:46px;" onclick="submitPlayCall('up')">
                ⬆️ CALL UP
              </button>
              <button class="btn" style="flex:1; background:#b91c1c; color:#fff; font-size:16px; font-weight:700; height:46px;" onclick="submitPlayCall('down')">
                ⬇️ CALL DOWN
              </button>
            </div>

            <div class="out-box" id="play-call-status" style="margin-top:14px; min-height:48px;">
              Select an asset, choose your horizon, and make your call.
            </div>
          </div>

          <!-- Chart Image Upload Card -->
          <div class="card" style="border: 1px solid var(--border);">
            <h3>📊 Chart Screenshot Model Reader</h3>
            <p style="font-size:12.5px; color:var(--mute)">
              Upload a candlestick chart image (green/red candles). The computer-vision neural model scans candle bodies and wicks to estimate forward direction.
            </p>

            <div style="margin:12px 0;">
              <input type="file" id="chart-file-input" accept="image/*" style="width:100%; padding:6px; font-size:12px;">
            </div>

            <div style="margin-bottom:12px;">
              <label style="display:flex; align-items:center; gap:8px; font-size:12px; cursor:pointer;">
                <input type="checkbox" id="chart-consent-checkbox" style="width:auto; margin:0;">
                <span>Allow anonymous chart image storage to improve model validation</span>
              </label>
            </div>

            <button class="btn btn-outline" style="width:100%;" onclick="uploadChartImage()">
              🔍 Analyze Chart Image
            </button>

            <div class="out-box" id="chart-upload-status" style="margin-top:12px; min-height:48px;">
              No image analyzed yet.
            </div>
          </div>
        </div>

        <!-- History & Performance Table Card -->
        <div class="card" style="margin-top:20px;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px;">
            <h3 style="margin:0;">📜 Your Live Prediction Track Record</h3>
            <button class="btn btn-outline" style="padding:4px 12px; font-size:12px;" onclick="loadPlayHistory()">Refresh History</button>
          </div>

          <div class="kpi-grid" style="margin-bottom:14px;">
            <div class="kpi-tile">
              <span class="kpi-name">Total Calls</span>
              <span class="kpi-val" id="play-stat-total">0</span>
            </div>
            <div class="kpi-tile">
              <span class="kpi-name">Wins</span>
              <span class="kpi-val" id="play-stat-wins" style="color:var(--emerald);">0</span>
            </div>
            <div class="kpi-tile">
              <span class="kpi-name">Win Rate</span>
              <span class="kpi-val" id="play-stat-winrate">0.0%</span>
            </div>
          </div>

          <div id="play-history-table-container">
            <span style="color:var(--mute); font-size:13px;">Loading prediction history...</span>
          </div>
        </div>
      </section>

      <!-- ALERTS, HOLDINGS & IPO RADAR SCREEN -->
      <section id="alerts-screen" class="pane">
        <h2>🔔 Market Radar, Price Alerts &amp; Holdings</h2>
        <p>Set automated price threshold alerts with push notifications (ntfy / phone), monitor portfolio stop-losses, and track new IPO filings.</p>

        <div class="grid-2" style="margin-top:16px;">
          <!-- Add Alert Rule Card -->
          <div class="card">
            <h3>⚡ Create Custom Price Alert</h3>
            <div class="grid" style="grid-template-columns: 1fr 1fr; gap:10px;">
              <div>
                <label>Symbol:
                  <input id="alert-rule-symbol" value="NIFTY" placeholder="e.g. NIFTY, RELIANCE, AMZN" style="text-transform:uppercase; font-weight:700;">
                </label>
              </div>
              <div>
                <label>Kind:
                  <select id="alert-rule-kind" style="width:100%; padding:8px; border-radius:6px; border:1px solid var(--border);">
                    <option value="above">Price Above</option>
                    <option value="below">Price Below</option>
                    <option value="move_1h_pct">1-Hour Move %</option>
                    <option value="move_1d_pct">1-Day Move %</option>
                    <option value="drop_from_ath_pct">Drop from ATH %</option>
                  </select>
                </label>
              </div>
            </div>
            <div class="grid" style="grid-template-columns: 1fr 1fr; gap:10px; margin-top:8px;">
              <div>
                <label>Threshold Value:
                  <input id="alert-rule-threshold" type="number" step="any" placeholder="e.g. 23000">
                </label>
              </div>
              <div>
                <label>Cooldown (Hours):
                  <input id="alert-rule-cooldown" type="number" value="4" min="0.5" step="0.5">
                </label>
              </div>
            </div>
            <button class="btn btn-gold" style="width:100%; margin-top:14px; height:42px;" onclick="submitAlertRule()">
              ➕ Add Alert Rule
            </button>
            <div class="out-box" id="alert-rule-status" style="margin-top:10px;">Ready to create alerts.</div>
          </div>

          <!-- Notification Channel Setup -->
          <div class="card">
            <h3>📱 Notification Channel (ntfy Push)</h3>
            <p style="font-size:12.5px; color:var(--mute)">
              Get instant alerts on your phone or browser using <a href="https://ntfy.sh" target="_blank" rel="noreferrer">ntfy.sh</a>. Subscribe to your unique topic name in the ntfy app.
            </p>
            <div style="margin-bottom:10px;">
              <label>ntfy Topic Name (8-64 chars):
                <input id="alert-ntfy-topic" placeholder="e.g. oracle_my_private_topic_9482">
              </label>
            </div>
            <div style="display:flex; gap:10px;">
              <button class="btn" style="flex:1;" onclick="saveAlertChannel()">Save Topic</button>
              <button class="btn btn-outline" style="flex:1;" onclick="sendTestAlert()">🔔 Send Test Alert</button>
            </div>
            <div class="out-box" id="alert-channel-status" style="margin-top:10px;">Configure your ntfy topic above.</div>
          </div>
        </div>

        <!-- Active Rules & Holdings -->
        <div class="grid-2" style="margin-top:16px;">
          <!-- Active Rules Table -->
          <div class="card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
              <h3 style="margin:0;">Active Alert Rules</h3>
              <button class="btn btn-outline" style="padding:2px 8px; font-size:11px;" onclick="loadAlertRules()">Refresh</button>
            </div>
            <div id="alert-rules-list-container">
              <span style="color:var(--mute); font-size:12.5px;">Loading active rules...</span>
            </div>
          </div>

          <!-- Portfolio Holdings Tracker -->
          <div class="card">
            <h3>💼 Portfolio Holdings &amp; Auto Stop-Loss</h3>
            <div class="grid" style="grid-template-columns: 1fr 1fr; gap:8px;">
              <div><label>Symbol<input id="hold-sym" value="RELIANCE" style="text-transform:uppercase;"></label></div>
              <div><label>Quantity<input id="hold-qty" type="number" value="10"></label></div>
            </div>
            <div class="grid" style="grid-template-columns: 1fr 1fr 1fr; gap:8px; margin-top:6px;">
              <div><label>Avg Price<input id="hold-price" type="number" step="any" placeholder="e.g. 1180"></label></div>
              <div><label>Stop %<input id="hold-stop" type="number" value="8.0"></label></div>
              <div><label>Target %<input id="hold-target" type="number" value="15.0"></label></div>
            </div>
            <button class="btn btn-outline" style="width:100%; margin-top:10px;" onclick="saveHolding()">Save Holding Target</button>
            <div id="holdings-list-container" style="margin-top:12px;">
              <span style="color:var(--mute); font-size:12.5px;">Loading holdings...</span>
            </div>
          </div>
        </div>

        <!-- Alert History Log & IPO Radar -->
        <div class="grid-2" style="margin-top:16px;">
          <div class="card">
            <h3>📜 Triggered Alert History</h3>
            <div id="alert-log-container" style="max-height:280px; overflow-y:auto;">
              <span style="color:var(--mute); font-size:12.5px;">Loading alert log...</span>
            </div>
          </div>

          <div class="card">
            <h3>🏢 Current &amp; Upcoming IPO Pipeline</h3>
            <div id="ipos-full-container" style="max-height:280px; overflow-y:auto;">
              <span style="color:var(--mute); font-size:12.5px;">Loading IPO pipeline...</span>
            </div>
          </div>
        </div>
      </section>
"""

# Insert sections right before <!-- WORKSPACE -->
workspace_comment = "      <!-- WORKSPACE -->"
if workspace_comment in html and 'id="prediction-game"' not in html:
    html = html.replace(workspace_comment, prediction_game_section + "\n" + workspace_comment, 1)

# 3. Add Terms checkbox in User Authentication (Workspace)
old_auth_box = """            <div style="display:flex; gap:10px;">
              <button class="btn" onclick="submitAuth('login')">Sign In</button>
              <button class="btn btn-gold" onclick="submitAuth('register')">Create Workspace</button>
            </div>"""

new_auth_box = """            <div style="margin:10px 0;">
              <label style="display:flex; align-items:center; gap:8px; font-size:12.5px; cursor:pointer;">
                <input type="checkbox" id="auth-terms-checkbox" style="width:auto; margin:0;">
                <span>I agree to the <a href="#" onclick="alert('ORACLE Terms v1.0: Educational and simulation platform only. All forecasts and market metrics are probabilistic estimates and not financial advice.'); return false;" style="color:var(--gold-dark); font-weight:600;">Terms of Service (v1.0)</a></span>
              </label>
            </div>
            <div style="display:flex; gap:10px;">
              <button class="btn" onclick="submitAuth('login')">Sign In</button>
              <button class="btn btn-gold" onclick="submitAuth('register')">Create Workspace</button>
            </div>"""

if old_auth_box in html and 'id="auth-terms-checkbox"' not in html:
    html = html.replace(old_auth_box, new_auth_box, 1)

# 4. Add Footer at bottom of main
old_main_end = """      </section>
    </main>"""

footer_html = """      </section>
      <!-- MANDATORY REGULATORY & SUPPORT FOOTER -->
      <footer style="margin-top:40px; padding:20px; border-top:1px solid var(--border); text-align:center; font-size:12.5px; color:var(--mute); background:var(--ivory-card); border-radius:12px;">
        <p style="margin:0 0 6px 0; font-weight:700; color:var(--ink);">Educational only, not financial advice.</p>
        <p style="margin:0; color:var(--ink-light);">Mental health support: <b>Tele-MANAS toll-free 14416</b> (24/7 National Tele-Mental Health Programme of India).</p>
      </footer>
    </main>"""

if old_main_end in html and "Tele-MANAS" not in html:
    html = html.replace(old_main_end, footer_html, 1)

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html.replace("\n", "\r\n"))

print("Successfully injected navigation, prediction game, alerts radar, terms checkbox, and footer.")
