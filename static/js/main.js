/**
 * main.js — PotatoSort AI Dashboard
 * Asynchronous fetch polling, state management, UI updates
 *
 * API endpoints consumed:
 *   GET  /api/status          → Full state snapshot (polled every 1s)
 *   POST /api/run-inspection  → Start inspection cycle
 *   GET  /api/result          → Latest result with thumbnails (after IDLE)
 *   POST /api/motor/toggle    → Toggle DC motor
 *   POST /api/servo/eject     → Trigger servo eject
 */

(function () {
  'use strict';

  // =========================================================================
  // 1. STATE
  // =========================================================================
  const state = {
    status:        'IDLE',
    lastStatus:    'IDLE',
    lastGrade:     null,
    sessionCount:  0,
    gradeCounts:   { A: 0, B: 0, C: 0 },
    motorOn:       false,
    simMode:       false,
    serialConn:    false,
    serialMock:    false,
    log:           [],   // inspection history (newest first)
    pollActive:    true,
    uptimeSec:     0,
  };

  // Grade-to-CSS class + colour mapping
  const GRADE_META = {
    A: { cls: 'grade-a', badgeCls: 'badge-grade-a', label: 'Grade A', color: '#10B981', desc: 'Premium' },
    B: { cls: 'grade-b', badgeCls: 'badge-grade-b', label: 'Grade B', color: '#F59E0B', desc: 'Processing' },
    C: { cls: 'grade-c', badgeCls: 'badge-grade-c', label: 'Grade C', color: '#EF4444', desc: 'Reject' },
  };

  const CLASS_CSS = {
    'Good':          'cls-good',
    'Lower Quality': 'cls-lower-quality',
    'Rotten':        'cls-rotten',
    'Scabs':         'cls-scabs',
    'Damaged':       'cls-damaged',
  };

  // =========================================================================
  // 2. DOM REFERENCES
  // =========================================================================
  const $ = (id) => document.getElementById(id);

  const dom = {
    // Header
    globalStatusPill:  $('globalStatusPill'),
    globalStatusText:  $('globalStatusText'),
    simBadge:          $('simBadge'),
    serialStatusBadge: $('serialStatusBadge'),
    serialStatusText:  $('serialStatusText'),
    btnExportCsv:      $('btnExportCsv'),

    // Camera HUD
    liveBadge:         $('liveBadge'),
    hudSessionCount:   $('hudSessionCount'),
    hudMode:           $('hudMode'),
    yoloStatusLabel:   $('yoloStatusLabel'),
    yoloConfTag:       $('yoloConfTag'),
    camFooterInfo:     $('camFooterInfo'),
    camSourceTag:      $('camSourceTag'),

    // Right panel
    blockyStatus:      $('blockyStatus'),
    blockyStatusText:  $('blockyStatusText'),
    btnStartSort:      $('btnStartSort'),

    // Grade cards
    gradeCardA:  $('gradeCardA'),
    gradeCardB:  $('gradeCardB'),
    gradeCardC:  $('gradeCardC'),
    gradeCountA: $('gradeCountA'),
    gradeCountB: $('gradeCountB'),
    gradeCountC: $('gradeCountC'),
    gradeConfA:  $('gradeConfA'),
    gradeConfB:  $('gradeConfB'),
    gradeConfC:  $('gradeConfC'),

    // Thumbnails
    thumbnailGrid: $('thumbnailGrid'),

    // Hardware tests
    btnMotorToggle: $('btnMotorToggle'),
    btnServoEject:  $('btnServoEject'),

    // Telemetry
    telemSessions:   $('telemSessions'),
    telemGradeA:     $('telemGradeA'),
    telemGradeB:     $('telemGradeB'),
    telemGradeC:     $('telemGradeC'),
    telemPlatform:   $('telemPlatform'),
    telemEngineMode: $('telemEngineMode'),
    telemUptime:     $('telemUptime'),

    // Audit
    auditTableBody: $('auditTableBody'),
    logItemCount:   $('logItemCount'),
    btnExportLog:   $('btnExportLog'),

    // Toast
    toastContainer: $('toastContainer'),
  };

  // =========================================================================
  // 3. TOAST NOTIFICATIONS
  // =========================================================================
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = 'toast';
    const iconColor = {
      success: '#34D399',
      warning: '#FBBF24',
      error:   '#F87171',
      info:    '#38BDF8',
    }[type] || '#38BDF8';

    toast.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="${iconColor}" stroke-width="2.5">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="16" x2="12" y2="12"/>
        <line x1="12" y1="8" x2="12.01" y2="8"/>
      </svg>
      <span>${message}</span>
    `;
    dom.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.transition = 'opacity 0.25s, transform 0.25s';
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(6px)';
      setTimeout(() => toast.remove(), 270);
    }, 3000);
  }

  // =========================================================================
  // 4. STATUS-DRIVEN UI UPDATES
  // =========================================================================

  const STATUS_CONFIG = {
    IDLE: {
      pillClass:    'status-idle',
      blockyClass:  'st-idle',
      pillText:     'IDLE',
      blockyText:   'IDLE — READY',
      yoloLabel:    '[ Waiting for inspection cycle… ]',
      yoloConf:     'READY',
      hudMode:      'IDLE',
      btnDisabled:  false,
    },
    INSPECTING: {
      pillClass:    'status-inspecting',
      blockyClass:  'st-inspecting',
      pillText:     'INSPECTING',
      blockyText:   'INSPECTING — Capturing 5 frames…',
      yoloLabel:    '[ Motor ON · Capturing 5 frames over 3s ]',
      yoloConf:     'RUNNING',
      hudMode:      'INSPECT',
      btnDisabled:  true,
    },
    EJECTING: {
      pillClass:    'status-ejecting',
      blockyClass:  'st-ejecting',
      pillText:     'EJECTING',
      blockyText:   'EJECTING — Running inference · Actuating servo…',
      yoloLabel:    '[ Running ONNX inference · Actuating servo ]',
      yoloConf:     'INFER',
      hudMode:      'EJECT',
      btnDisabled:  true,
    },
    ERROR: {
      pillClass:    'status-error',
      blockyClass:  'st-error',
      pillText:     'ERROR',
      blockyText:   'ERROR — Check logs',
      yoloLabel:    '[ Error — see system logs for details ]',
      yoloConf:     'ERROR',
      hudMode:      'ERR',
      btnDisabled:  false,
    },
  };

  function applyStatusUI(status) {
    const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.IDLE;

    // Global status pill
    dom.globalStatusPill.className = `status-pill ${cfg.pillClass}`;
    dom.globalStatusText.textContent = cfg.pillText;

    // Blocky banner
    dom.blockyStatus.className = `blocky-status ${cfg.blockyClass}`;
    dom.blockyStatusText.textContent = cfg.blockyText;

    // Live badge
    if (status === 'IDLE' || status === 'ERROR') {
      dom.liveBadge.classList.remove('active');
    } else {
      dom.liveBadge.classList.add('active');
    }

    // YOLOv8 overlay
    dom.yoloStatusLabel.textContent = cfg.yoloLabel;
    dom.yoloConfTag.textContent = cfg.yoloConf;

    // HUD mode
    dom.hudMode.textContent = cfg.hudMode;

    // Start button
    dom.btnStartSort.disabled = cfg.btnDisabled;

    // Add spinner SVG to button while active
    if (cfg.btnDisabled) {
      dom.btnStartSort.innerHTML = `
        <svg class="spinner" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
        </svg>
        ${cfg.pillText}…
      `;
    } else {
      dom.btnStartSort.innerHTML = `
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5 3 19 12 5 21 5 3"/>
        </svg>
        START SORTING CYCLE
      `;
    }
  }

  // =========================================================================
  // 5. GRADE UI UPDATES
  // =========================================================================

  function updateGradeUI(gradeCounts, lastGrade, lastResult) {
    // Update count labels
    dom.gradeCountA.textContent = `${gradeCounts.A || 0} runs`;
    dom.gradeCountB.textContent = `${gradeCounts.B || 0} runs`;
    dom.gradeCountC.textContent = `${gradeCounts.C || 0} runs`;

    // Remove active from all, then apply to last grade
    [dom.gradeCardA, dom.gradeCardB, dom.gradeCardC].forEach(c =>
      c.classList.remove('active')
    );

    if (lastGrade && lastResult) {
      const conf = ((lastResult.avg_confidence || 0) * 100).toFixed(1);
      const confText = `${conf}% avg conf`;
      const simNote = lastResult.sim_mode ? ' (SIM)' : '';

      if (lastGrade === 'A') {
        dom.gradeCardA.classList.add('active');
        dom.gradeConfA.textContent = confText + simNote;
      } else if (lastGrade === 'B') {
        dom.gradeCardB.classList.add('active');
        dom.gradeConfB.textContent = confText + simNote;
      } else if (lastGrade === 'C') {
        dom.gradeCardC.classList.add('active');
        dom.gradeConfC.textContent = confText + simNote;
      }
    }
  }

  // =========================================================================
  // 6. THUMBNAIL GALLERY
  // =========================================================================

  function clearThumbnails() {
    for (let i = 1; i <= 5; i++) {
      const slot = $(`thumb${i}`);
      if (!slot) continue;
      slot.innerHTML = `<div class="thumb-label">F${i}</div>`;
    }
  }

  function renderThumbnails(thumbnails, frameDetail) {
    if (!thumbnails || !thumbnails.length) return;

    for (let i = 0; i < 5; i++) {
      const slot = $(`thumb${i + 1}`);
      if (!slot) continue;

      const src = thumbnails[i];
      const detail = frameDetail && frameDetail[i];
      const cls  = detail ? (CLASS_CSS[detail.class] || 'cls-pending') : 'cls-pending';
      const conf = detail ? `${(detail.confidence * 100).toFixed(0)}%` : '';
      const lbl  = detail ? detail.class.slice(0, 4).toUpperCase() : 'PEND';

      slot.innerHTML = `
        ${src ? `<img src="${src}" alt="Frame ${i + 1}" loading="lazy">` : ''}
        <span class="thumb-class ${cls}">${lbl} ${conf}</span>
        <div class="thumb-label">F${i + 1}</div>
      `;
    }
  }

  // =========================================================================
  // 7. TELEMETRY STRIP UPDATES
  // =========================================================================

  function updateTelemetry(statusSnap) {
    dom.telemSessions.textContent  = statusSnap.session_count || 0;
    dom.telemGradeA.textContent    = (statusSnap.grade_counts && statusSnap.grade_counts.A) || 0;
    dom.telemGradeB.textContent    = (statusSnap.grade_counts && statusSnap.grade_counts.B) || 0;
    dom.telemGradeC.textContent    = (statusSnap.grade_counts && statusSnap.grade_counts.C) || 0;
    dom.hudSessionCount.textContent = statusSnap.session_count || 0;

    if (statusSnap.hw) {
      dom.telemPlatform.textContent = statusSnap.hw.mock_mode ? 'DEV' : 'PI5';
    }
    if (statusSnap.engine) {
      dom.telemEngineMode.textContent = statusSnap.engine.sim_mode ? 'SIM' : 'ONNX';
      dom.simBadge.style.display = statusSnap.engine.sim_mode ? 'inline-flex' : 'none';
    }
    if (statusSnap.serial) {
      const s = statusSnap.serial;
      if (s.mock_mode) {
        dom.serialStatusBadge.className = 'serial-status mock';
        dom.serialStatusText.textContent = 'ESP32 MOCK';
      } else if (s.connected) {
        dom.serialStatusBadge.className = 'serial-status connected';
        dom.serialStatusText.textContent = `ESP32 ${s.port || ''}`;
      } else {
        dom.serialStatusBadge.className = 'serial-status disconnected';
        dom.serialStatusText.textContent = 'ESP32 —';
      }

      // Update cam footer
      dom.camFooterInfo.textContent = s.mock_mode
        ? 'Synthetic / OpenCV feed — No Pi hardware'
        : 'IMX219 · 640×480 · picamera2 (libcamera)';
    }
  }

  // =========================================================================
  // 8. MOTOR STATE
  // =========================================================================

  function updateMotorUI(isOn) {
    state.motorOn = isOn;
    if (isOn) {
      dom.btnMotorToggle.classList.add('motor-on');
      dom.btnMotorToggle.querySelector('svg').style.color = '#fff';
    } else {
      dom.btnMotorToggle.classList.remove('motor-on');
    }
  }

  // =========================================================================
  // 9. AUDIT TABLE
  // =========================================================================

  function renderAuditTable() {
    if (!dom.auditTableBody) return;
    dom.auditTableBody.innerHTML = '';
    const rows = state.log.slice(0, 30);

    if (dom.logItemCount) {
      dom.logItemCount.textContent = `${state.log.length} session${state.log.length !== 1 ? 's' : ''}`;
    }

    rows.forEach(entry => {
      const meta = GRADE_META[entry.grade] || GRADE_META.C;
      const tr = document.createElement('tr');
      const classesStr = (entry.frame_classes || []).join(', ');
      const confPct = ((entry.avg_confidence || 0) * 100).toFixed(1);

      tr.innerHTML = `
        <td class="mono" style="font-size:0.65rem">${entry.ts}</td>
        <td class="mono" style="font-weight:700;color:#0F172A">#${entry.session_n}</td>
        <td><span class="badge-pill-sm ${meta.badgeCls}">${meta.label}</span></td>
        <td class="mono">${confPct}%</td>
        <td style="font-size:0.65rem;color:#64748B;max-width:220px;overflow:hidden;text-overflow:ellipsis">${classesStr}</td>
        <td class="mono" style="font-size:0.65rem">${entry.serial_tx ? '✓ TX' : '— skip'}</td>
        <td style="font-size:0.65rem;color:${entry.sim_mode ? '#F59E0B' : '#10B981'}">${entry.sim_mode ? 'SIM' : 'LIVE'}</td>
      `;
      dom.auditTableBody.appendChild(tr);
    });
  }

  // =========================================================================
  // 10. API POLLING (every 1 second)
  // =========================================================================

  let _lastResultFinishedAt = null;

  async function pollStatus() {
    try {
      const resp = await fetch('/api/status', { signal: AbortSignal.timeout(3000) });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const snap = await resp.json();

      const newStatus = snap.status || 'IDLE';

      // Only call applyStatusUI when status changes (avoids DOM thrashing)
      if (newStatus !== state.lastStatus) {
        applyStatusUI(newStatus);
        state.lastStatus = newStatus;

        // When transitioning back to IDLE after an active cycle → fetch result
        if (newStatus === 'IDLE' && ['INSPECTING','EJECTING'].includes(state.status)) {
          fetchAndRenderResult();
        }

        // Notify user of state transitions
        if (newStatus === 'INSPECTING') showToast('Inspection cycle started — motor ON', 'info');
        if (newStatus === 'EJECTING')   showToast('Inference running — servo ejecting', 'info');
        if (newStatus === 'ERROR')      showToast(`Error: ${snap.error || 'unknown'}`, 'error');
      }

      state.status        = newStatus;
      state.sessionCount  = snap.session_count || 0;
      state.gradeCounts   = snap.grade_counts  || { A:0, B:0, C:0 };
      state.lastGrade     = snap.last_grade;
      state.lastResult    = snap.last_result;

      updateMotorUI(snap.hw && snap.hw.motor_on);
      updateTelemetry(snap);
      updateGradeUI(state.gradeCounts, state.lastGrade, state.lastResult);

    } catch (err) {
      if (err.name !== 'AbortError') {
        console.warn('[poll] status error:', err.message);
      }
    }
  }

  async function fetchAndRenderResult() {
    try {
      const resp = await fetch('/api/result', { signal: AbortSignal.timeout(5000) });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const result = await resp.json();

      if (!result.grade) return;

      const meta = GRADE_META[result.grade] || GRADE_META.C;
      showToast(`Grade ${result.grade} — ${meta.desc}  (${((result.result?.avg_confidence||0)*100).toFixed(1)}% conf)`, 
                result.grade === 'A' ? 'success' : result.grade === 'B' ? 'warning' : 'error');

      renderThumbnails(
        result.thumbnails || [],
        result.result?.frame_detail || []
      );
      updateGradeUI(result.grade_counts || {}, result.grade, result.result);

      // Add to audit log
      const now = new Date();
      const ts  = now.toLocaleTimeString('en-GB', { hour12: false, hour:'2-digit', minute:'2-digit', second:'2-digit' });
      state.log.unshift({
        ts:             ts,
        session_n:      result.session_count || state.sessionCount,
        grade:          result.grade,
        avg_confidence: result.result?.avg_confidence || 0,
        frame_classes:  result.result?.frame_classes || [],
        serial_tx:      true,
        sim_mode:       result.result?.sim_mode || false,
      });
      if (state.log.length > 50) state.log.pop();
      renderAuditTable();

    } catch (err) {
      console.warn('[result] fetch error:', err.message);
    }
  }

  // Start polling
  setInterval(pollStatus, 1000);

  // =========================================================================
  // 11. UPTIME COUNTER (client-side, since startup)
  // =========================================================================
  const _appStartTime = Date.now();
  setInterval(() => {
    const elapsed = Math.floor((Date.now() - _appStartTime) / 1000);
    const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
    const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
    const s = String(elapsed % 60).padStart(2, '0');
    if (dom.telemUptime) dom.telemUptime.textContent = `${h}:${m}:${s}`;
  }, 1000);

  // =========================================================================
  // 12. BUTTON HANDLERS
  // =========================================================================

  // — START SORTING CYCLE ——————————————————————————————————————————————————
  dom.btnStartSort.addEventListener('click', async () => {
    if (state.status !== 'IDLE') {
      showToast('Cycle already running — wait for IDLE', 'warning');
      return;
    }

    clearThumbnails();

    try {
      dom.btnStartSort.disabled = true;
      const resp = await fetch('/api/run-inspection', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({}),
        signal:  AbortSignal.timeout(5000),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showToast(data.error || 'Could not start cycle', 'error');
        dom.btnStartSort.disabled = false;
      } else {
        // UI will auto-update via poll
      }
    } catch (err) {
      showToast(`Network error: ${err.message}`, 'error');
      dom.btnStartSort.disabled = false;
    }
  });

  // — MOTOR TOGGLE ——————————————————————————————————————————————————————————
  dom.btnMotorToggle.addEventListener('click', async () => {
    if (state.status !== 'IDLE') {
      showToast('Cannot toggle motor during inspection', 'warning');
      return;
    }
    try {
      dom.btnMotorToggle.disabled = true;
      const resp = await fetch('/api/motor/toggle', {
        method: 'POST',
        signal: AbortSignal.timeout(3000),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showToast(data.error || 'Motor toggle failed', 'error');
      } else {
        const on = data.motor === 'on';
        updateMotorUI(on);
        showToast(`Motor GPIO 17 → ${data.motor.toUpperCase()}`, 'info');
      }
    } catch (err) {
      showToast(`Motor error: ${err.message}`, 'error');
    } finally {
      dom.btnMotorToggle.disabled = false;
    }
  });

  // — SERVO EJECT ───────────────────────────────────────────────────────────
  dom.btnServoEject.addEventListener('click', async () => {
    if (state.status !== 'IDLE') {
      showToast('Cannot trigger servo during inspection', 'warning');
      return;
    }
    try {
      dom.btnServoEject.disabled = true;
      dom.btnServoEject.textContent = 'Ejecting…';
      const resp = await fetch('/api/servo/eject', {
        method: 'POST',
        signal: AbortSignal.timeout(3000),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showToast(data.error || 'Servo eject failed', 'error');
      } else {
        showToast('Servo GPIO 12 → 0° → 90° → 0°', 'info');
        // Re-enable after ~900ms (eject duration + margin)
        setTimeout(() => {
          dom.btnServoEject.disabled = false;
          dom.btnServoEject.innerHTML = `
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M12 2v20M2 12h20"/><circle cx="12" cy="12" r="4"/>
            </svg>
            Servo Eject GPIO 12
          `;
        }, 950);
        return;
      }
    } catch (err) {
      showToast(`Servo error: ${err.message}`, 'error');
    }
    dom.btnServoEject.disabled = false;
    dom.btnServoEject.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <path d="M12 2v20M2 12h20"/><circle cx="12" cy="12" r="4"/>
      </svg>
      Servo Eject GPIO 12
    `;
  });

  // — EXPORT CSV ────────────────────────────────────────────────────────────
  function exportCsv() {
    const headers = ['Timestamp','Session','Grade','Avg_Confidence','Frame_Classes','Serial_TX','Sim_Mode'];
    const rows = state.log.map(e => [
      `"${e.ts}"`,
      e.session_n,
      `"${e.grade}"`,
      `"${((e.avg_confidence||0)*100).toFixed(1)}%"`,
      `"${(e.frame_classes||[]).join('; ')}"`,
      e.serial_tx ? 'YES' : 'NO',
      e.sim_mode  ? 'SIM' : 'LIVE',
    ]);
    if (!rows.length) {
      showToast('No inspection data to export', 'warning');
      return;
    }
    const csv = 'data:text/csv;charset=utf-8,'
      + headers.join(',') + '\n'
      + rows.map(r => r.join(',')).join('\n');
    const link = document.createElement('a');
    link.href = encodeURI(csv);
    link.download = `potato_grade_log_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('Inspection log exported as CSV', 'success');
  }

  if (dom.btnExportCsv)  dom.btnExportCsv.addEventListener('click',  exportCsv);
  if (dom.btnExportLog)  dom.btnExportLog.addEventListener('click',  exportCsv);

  // — CAPTURE SPEED SLIDER ──────────────────────────────────────────────────
  const speedSlider = $('captureSpeedSlider');
  const speedLabel  = $('speedValueLabel');
  
  if (speedSlider) {
    speedSlider.addEventListener('input', (e) => {
      speedLabel.textContent = `${parseFloat(e.target.value).toFixed(1)}s`;
    });
    
    speedSlider.addEventListener('change', async (e) => {
      const newSpan = parseFloat(e.target.value);
      try {
        speedSlider.disabled = true;
        const resp = await fetch('/api/settings/capture-span', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ capture_span: newSpan }),
          signal: AbortSignal.timeout(3000),
        });
        const data = await resp.json();
        if (!resp.ok) {
          showToast(data.error || 'Failed to update capture speed', 'error');
        } else {
          showToast(`Capture speed set to ${data.capture_span.toFixed(1)}s`, 'success');
        }
      } catch (err) {
        showToast(`Error updating speed: ${err.message}`, 'error');
      } finally {
        speedSlider.disabled = false;
      }
    });
  }

  // =========================================================================
  // 13. INIT
  // =========================================================================
  applyStatusUI('IDLE');
  clearThumbnails();
  pollStatus();   // immediate first poll
  showToast('Station #01 Online — Potato Sorter AI Ready', 'success');

})();
