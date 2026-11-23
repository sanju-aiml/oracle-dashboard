// Streaming chat client for index.html. Shows tool calls, per-answer verification badge, fallback banner and approve/reject buttons.
async function askBot(message, history, onEvent) {
  try {
    const res = await fetch('/api/chat?stream=true', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message, history: history || []})
    });
    if (!res.ok) {
      // Fallback to non-streaming if stream not supported
      const errData = await res.json().catch(() => ({}));
      onEvent({
        type: 'final',
        text: errData.detail || ('Error ' + res.status),
        mode: 'error',
        verified: false,
        warnings: [res.statusText || 'HTTP Error'],
        needs_approval: []
      });
      return;
    }
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = '';
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 2);
        if (line.startsWith('data:')) {
          try {
            onEvent(JSON.parse(line.slice(5).trim()));
          } catch (e) {
            console.error('Parse error in SSE data', e);
          }
        }
      }
    }
  } catch (err) {
    onEvent({
      type: 'final',
      text: 'Network error communicating with AI server.',
      mode: 'error',
      verified: false,
      warnings: [err.message],
      needs_approval: []
    });
  }
}

function renderEvent(box, ev) {
  if (ev.type === 'tool_call') {
    const toolDiv = document.createElement('div');
    toolDiv.className = 'tool-call-line';
    toolDiv.style.fontSize = '12px';
    toolDiv.style.color = '#795548';
    toolDiv.style.background = '#fbf0e4';
    toolDiv.style.padding = '4px 10px';
    toolDiv.style.borderRadius = '6px';
    toolDiv.style.margin = '4px 0';
    toolDiv.textContent = '⚙️ Calling tool ' + ev.tool + (ev.args ? ' ' + JSON.stringify(ev.args) : '');
    box.appendChild(toolDiv);
  }
  if (ev.type === 'tool_result') {
    const resDiv = document.createElement('div');
    resDiv.className = 'tool-result-line';
    resDiv.style.fontSize = '11.5px';
    resDiv.style.color = '#555';
    resDiv.style.padding = '2px 10px 4px 16px';
    resDiv.textContent = '↳ status: ' + ((ev.result && ev.result.status) || 'ok');
    box.appendChild(resDiv);
  }
  if (ev.type === 'final') {
    // Model output wrapper
    const botMsg = document.createElement('div');
    botMsg.className = 'msg-bot';
    // STRICT REQUIREMENT: Render model output with textContent only
    botMsg.textContent = ev.text;
    box.appendChild(botMsg);

    // Verification badge or fallback banner
    const badgeWrap = document.createElement('div');
    badgeWrap.style.margin = '4px 0 10px 4px';
    const badge = document.createElement('span');
    badge.style.fontSize = '11.5px';
    badge.style.padding = '2px 8px';
    badge.style.borderRadius = '4px';
    badge.style.display = 'inline-block';

    if (ev.mode === 'fallback') {
      badge.style.background = '#fff3cd';
      badge.style.color = '#856404';
      badge.style.border = '1px solid #ffeeba';
      badge.textContent = '⚠️ Fallback (AI model offline)';
    } else if (ev.verified) {
      badge.style.background = '#d4edda';
      badge.style.color = '#155724';
      badge.style.border = '1px solid #c3e6cb';
      badge.textContent = '✅ Figures verified against tools';
    } else {
      badge.style.background = '#fff3cd';
      badge.style.color = '#856404';
      badge.style.border = '1px solid #ffeeba';
      badge.textContent = '⚠️ ' + (ev.warnings && ev.warnings.length ? ev.warnings.join('; ') : 'Unverified figures');
    }
    badgeWrap.appendChild(badge);
    box.appendChild(badgeWrap);

    // Proposed orders with Approve / Reject buttons
    (ev.needs_approval || []).forEach(o => {
      const orderBox = document.createElement('div');
      orderBox.className = 'pending-order-card';
      orderBox.style.background = '#f8f9fa';
      orderBox.style.border = '1px solid #ced4da';
      orderBox.style.padding = '10px 14px';
      orderBox.style.borderRadius = '8px';
      orderBox.style.margin = '8px 0';
      orderBox.id = 'approval-' + o.id;

      const desc = document.createElement('span');
      desc.style.fontWeight = '600';
      desc.textContent = `Proposed Order ${o.id}: ${(o.side || '').toUpperCase()} ${o.qty} ${o.symbol} `;
      orderBox.appendChild(desc);

      const btnApprove = document.createElement('button');
      btnApprove.className = 'btn btn-gold';
      btnApprove.style.padding = '3px 10px';
      btnApprove.style.fontSize = '12px';
      btnApprove.style.marginLeft = '8px';
      btnApprove.textContent = 'Approve';
      btnApprove.onclick = () => decide(o.id, 'approve');
      orderBox.appendChild(btnApprove);

      const btnReject = document.createElement('button');
      btnReject.className = 'btn btn-outline';
      btnReject.style.padding = '3px 10px';
      btnReject.style.fontSize = '12px';
      btnReject.style.marginLeft = '6px';
      btnReject.textContent = 'Reject';
      btnReject.onclick = () => decide(o.id, 'reject');
      orderBox.appendChild(btnReject);

      box.appendChild(orderBox);
    });
  }
}

async function decide(id, action) {
  try {
    const r = await fetch(`/api/approvals/${id}/${action}`, {method: 'POST'});
    const data = await r.json();
    const card = document.getElementById('approval-' + id);
    if (card) {
      card.innerHTML = '';
      const statusSpan = document.createElement('span');
      statusSpan.style.fontWeight = 'bold';
      statusSpan.style.color = action === 'approve' ? '#2e7d32' : '#c62828';
      statusSpan.textContent = `Order ${id} ${action}d: ${JSON.stringify(data)}`;
      card.appendChild(statusSpan);
    }
  } catch (err) {
    alert('Action failed: ' + err.message);
  }
}
