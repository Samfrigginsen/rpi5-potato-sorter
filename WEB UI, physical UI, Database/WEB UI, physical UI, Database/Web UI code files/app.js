/**
 * POTATO SORTER — CLEAN DASHBOARD
 * Simulation Engine (Raspberry Pi 5 + YOLOv8)
 * Redesigned for 1920×1080 single-viewport layout
 */

(function () {
  'use strict';

  // =========================================================================
  // 1. STATE STORE
  // =========================================================================
  const state = {
    isRunning: true,
    totalScanned: 1240,
    speed: 0.40,

    bins: {
      reject: 220,
      small:  310,
      medium: 480,
      large:  230
    },

    telemetry: {
      temp:        42.4,
      humidity:    65,
      cpu:         28,
      inferenceMs: 14.2,
      fps:         29.9
    },

    showBoxes:       true,
    showScanlines:   true,
    simulateDefects: true,

    recentEvents: []
  };

  // Pre-populate audit log
  const initialLogs = [
    { time: '00:02:41.108', id: 'PT-10492', cls: 'Healthy', size: 'Medium',         conf: '95%', bin: 'Medium', act: 'Chute #3' },
    { time: '00:02:39.840', id: 'PT-10491', cls: 'Reject',  size: 'Defect (Blight)', conf: '91%', bin: 'Reject', act: 'Gate #1'  },
    { time: '00:02:38.215', id: 'PT-10490', cls: 'Healthy', size: 'Large',           conf: '96%', bin: 'Large',  act: 'Chute #4' },
    { time: '00:02:36.910', id: 'PT-10489', cls: 'Healthy', size: 'Small',           conf: '93%', bin: 'Small',  act: 'Chute #2' },
    { time: '00:02:35.340', id: 'PT-10488', cls: 'Healthy', size: 'Medium',         conf: '95%', bin: 'Medium', act: 'Chute #3' },
    { time: '00:02:33.890', id: 'PT-10487', cls: 'Healthy', size: 'Medium',         conf: '92%', bin: 'Medium', act: 'Chute #3' },
    { time: '00:02:32.410', id: 'PT-10486', cls: 'Reject',  size: 'Defect (Rot)',    conf: '90%', bin: 'Reject', act: 'Gate #1'  },
    { time: '00:02:30.980', id: 'PT-10485', cls: 'Healthy', size: 'Large',           conf: '97%', bin: 'Large',  act: 'Chute #4' }
  ];
  state.recentEvents = [...initialLogs];

  // =========================================================================
  // 2. DOM REFERENCES
  // =========================================================================
  const dom = {
    // Header
    systemStatusPill: document.getElementById('systemStatusPill'),
    statusPillText:   document.getElementById('statusPillText'),
    uptimeDisplay:    document.getElementById('uptimeDisplay'),
    inferenceLatency: document.getElementById('inferenceLatency'),

    // Camera
    conveyorCanvas:      document.getElementById('conveyorCanvas'),
    liveBadgeIndicator:  document.getElementById('liveBadgeIndicator'),
    camFps:              document.getElementById('camFps'),
    yoloOverlayPill:     document.getElementById('yoloOverlayPill'),
    yoloDetectionLabel:  document.getElementById('yoloDetectionLabel'),
    yoloConfPill:        document.getElementById('yoloConfPill'),
    chkShowBoxes:        document.getElementById('chkShowBoxes'),
    chkShowScanlines:    document.getElementById('chkShowScanlines'),
    chkSimulateDefects:  document.getElementById('chkSimulateDefects'),
    feedStatusText:      document.getElementById('feedStatusText'),

    // Key Metrics
    metricTotalScanned:  document.getElementById('metricTotalScanned'),
    metricConveyorSpeed: document.getElementById('metricConveyorSpeed'),
    metricHealthyRatio:  document.getElementById('metricHealthyRatio'),
    healthyCountSub:     document.getElementById('healthyCountSub'),
    totalCountSub:       document.getElementById('totalCountSub'),
    speedStatusText:     document.getElementById('speedStatusText'),
    qualityGradeBadge:   document.getElementById('qualityGradeBadge'),

    // Bin Counts
    countBinReject: document.getElementById('countBinReject'),
    countBinSmall:  document.getElementById('countBinSmall'),
    countBinMedium: document.getElementById('countBinMedium'),
    countBinLarge:  document.getElementById('countBinLarge'),

    pctBinReject: document.getElementById('pctBinReject'),
    pctBinSmall:  document.getElementById('pctBinSmall'),
    pctBinMedium: document.getElementById('pctBinMedium'),
    pctBinLarge:  document.getElementById('pctBinLarge'),

    progressBinReject: document.getElementById('progressBinReject'),
    progressBinSmall:  document.getElementById('progressBinSmall'),
    progressBinMedium: document.getElementById('progressBinMedium'),
    progressBinLarge:  document.getElementById('progressBinLarge'),

    // Distribution bar
    segReject:      document.getElementById('segReject'),
    segSmall:       document.getElementById('segSmall'),
    segMedium:      document.getElementById('segMedium'),
    segLarge:       document.getElementById('segLarge'),
    distSummaryText:document.getElementById('distSummaryText'),
    legPctReject:   document.getElementById('legPctReject'),
    legPctSmall:    document.getElementById('legPctSmall'),
    legPctMedium:   document.getElementById('legPctMedium'),
    legPctLarge:    document.getElementById('legPctLarge'),

    // Telemetry strip
    metricSysTemp:  document.getElementById('metricSysTemp'),
    metricHumidity: document.getElementById('metricHumidity'),
    metricCpuLoad:  document.getElementById('metricCpuLoad'),

    // Controls
    btnStartConveyor: document.getElementById('btnStartConveyor'),
    btnStopConveyor:  document.getElementById('btnStopConveyor'),
    btnResetCounters: document.getElementById('btnResetCounters'),
    btnExportCsv:     document.getElementById('btnExportCsv'),

    // Audit
    auditTableBody: document.getElementById('auditTableBody'),
    logItemCount:   document.getElementById('logItemCount'),

    // Modal
    resetModal:     document.getElementById('resetModal'),
    btnCancelReset: document.getElementById('btnCancelReset'),
    btnConfirmReset:document.getElementById('btnConfirmReset'),

    // Toast
    toastContainer: document.getElementById('toastContainer')
  };

  // =========================================================================
  // 3. UI UPDATE FUNCTIONS
  // =========================================================================

  function fmt(n) {
    return new Intl.NumberFormat().format(n);
  }

  function updateDashboardUI() {
    const total = state.totalScanned;
    const { reject, small, medium, large } = state.bins;
    const healthyTotal = small + medium + large;

    // Total Scanned
    dom.metricTotalScanned.textContent = fmt(total);
    dom.totalCountSub.textContent       = fmt(total);
    dom.healthyCountSub.textContent     = fmt(healthyTotal);
    dom.distSummaryText.textContent     = `${fmt(total)} total pieces`;

    // Healthy Ratio
    let ratio = total > 0 ? Math.round((healthyTotal / total) * 100) : 100;
    dom.metricHealthyRatio.textContent = `${ratio}%`;

    // Ratio color
    if (ratio >= 80) {
      dom.metricHealthyRatio.style.color = '#10B981';
      dom.qualityGradeBadge.innerHTML = `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Grade A Commercial`;
      dom.qualityGradeBadge.style.cssText = 'background:#ECFDF5;color:#065F46;border-color:#A7F3D0;display:inline-flex;align-items:center;gap:0.25rem;font-size:0.65rem;font-weight:700;padding:0.15rem 0.5rem;border-radius:4px;border:1px solid;width:fit-content;';
    } else if (ratio >= 65) {
      dom.metricHealthyRatio.style.color = '#F59E0B';
      dom.qualityGradeBadge.innerHTML = `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="9" x2="12" y2="13"/><circle cx="12" cy="17" r="1"/></svg> Grade B Processing`;
      dom.qualityGradeBadge.style.cssText = 'background:#FFFBEB;color:#B45309;border-color:#FDE68A;display:inline-flex;align-items:center;gap:0.25rem;font-size:0.65rem;font-weight:700;padding:0.15rem 0.5rem;border-radius:4px;border:1px solid;width:fit-content;';
    } else {
      dom.metricHealthyRatio.style.color = '#EF4444';
      dom.qualityGradeBadge.innerHTML = `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/></svg> High Reject Warning`;
      dom.qualityGradeBadge.style.cssText = 'background:#FEF2F2;color:#991B1B;border-color:#FECACA;display:inline-flex;align-items:center;gap:0.25rem;font-size:0.65rem;font-weight:700;padding:0.15rem 0.5rem;border-radius:4px;border:1px solid;width:fit-content;';
    }

    // Conveyor Speed
    dom.metricConveyorSpeed.textContent = state.speed.toFixed(2);

    // Bin Counts
    dom.countBinReject.textContent = fmt(reject);
    dom.countBinSmall.textContent  = fmt(small);
    dom.countBinMedium.textContent = fmt(medium);
    dom.countBinLarge.textContent  = fmt(large);

    // Percentages
    const pR = total > 0 ? ((reject / total) * 100).toFixed(1) : '0.0';
    const pS = total > 0 ? ((small  / total) * 100).toFixed(1) : '0.0';
    const pM = total > 0 ? ((medium / total) * 100).toFixed(1) : '0.0';
    const pL = total > 0 ? ((large  / total) * 100).toFixed(1) : '0.0';

    dom.pctBinReject.textContent = `${pR}%`;
    dom.pctBinSmall.textContent  = `${pS}%`;
    dom.pctBinMedium.textContent = `${pM}%`;
    dom.pctBinLarge.textContent  = `${pL}%`;

    dom.progressBinReject.style.width = `${pR}%`;
    dom.progressBinSmall.style.width  = `${pS}%`;
    dom.progressBinMedium.style.width = `${pM}%`;
    dom.progressBinLarge.style.width  = `${pL}%`;

    dom.segReject.style.width = `${pR}%`;
    dom.segSmall.style.width  = `${pS}%`;
    dom.segMedium.style.width = `${pM}%`;
    dom.segLarge.style.width  = `${pL}%`;

    dom.legPctReject.textContent = `${pR}%`;
    dom.legPctSmall.textContent  = `${pS}%`;
    dom.legPctMedium.textContent = `${pM}%`;
    dom.legPctLarge.textContent  = `${pL}%`;
  }

  function renderAuditTable() {
    dom.auditTableBody.innerHTML = '';
    const rows = state.recentEvents.slice(0, 25);
    if (dom.logItemCount) {
      dom.logItemCount.textContent = `${rows.length} entries`;
    }

    rows.forEach(item => {
      const tr = document.createElement('tr');
      let badgeCls = 'badge-medium';
      if      (item.bin === 'Reject') badgeCls = 'badge-reject';
      else if (item.bin === 'Small')  badgeCls = 'badge-small';
      else if (item.bin === 'Large')  badgeCls = 'badge-large';

      tr.innerHTML = `
        <td class="mono">${item.time}</td>
        <td class="mono" style="font-weight:700;color:#0F172A">${item.id}</td>
        <td style="font-weight:600;color:${item.cls === 'Reject' ? '#EF4444' : '#10B981'}">${item.cls}</td>
        <td>${item.size}</td>
        <td class="mono">${item.conf}</td>
        <td><span class="badge-pill-sm ${badgeCls}">${item.bin}</span></td>
        <td style="color:#94A3B8;font-size:0.65rem">${item.act}</td>
      `;
      dom.auditTableBody.appendChild(tr);
    });
  }

  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = 'toast';
    const colors = { success: '#34D399', warning: '#FBBF24', info: '#38BDF8' };
    const color = colors[type] || colors.info;
    toast.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2.5">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
      </svg>
      <span>${message}</span>
    `;
    dom.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.transition = 'opacity 0.25s, transform 0.25s';
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(6px)';
      setTimeout(() => toast.remove(), 260);
    }, 2800);
  }

  // =========================================================================
  // 4. CANVAS — Conveyor + YOLOv8 Simulation
  // =========================================================================
  const canvas = dom.conveyorCanvas;
  const ctx    = canvas.getContext('2d');
  let cW = 800, cH = 500;

  function resizeCanvas() {
    const parent = canvas.parentElement;
    cW = parent.clientWidth;
    cH = parent.clientHeight;
    canvas.width  = cW;
    canvas.height = cH;
  }
  window.addEventListener('resize', resizeCanvas);
  resizeCanvas();

  // ── Potato Object ──
  class Potato {
    constructor(startX) { this.reset(startX); }

    reset(x = -55) {
      this.x = x;
      this.y = cH * 0.5 + (Math.random() * 24 - 12);

      const r = Math.random();
      if (r < 0.18 && state.simulateDefects) {
        this.category  = 'Reject';
        this.sizeName  = 'Defect (Blight)';
        this.rX = 20 + Math.random() * 5;
        this.rY = 15 + Math.random() * 4;
        this.conf      = Math.floor(88 + Math.random() * 10);
        this.blemish   = true;
      } else if (r < 0.43) {
        this.category  = 'Small';
        this.sizeName  = '<50mm';
        this.rX = 16 + Math.random() * 4;
        this.rY = 13 + Math.random() * 3;
        this.conf      = Math.floor(91 + Math.random() * 8);
        this.blemish   = false;
      } else if (r < 0.82) {
        this.category  = 'Medium';
        this.sizeName  = '50-75mm';
        this.rX = 24 + Math.random() * 5;
        this.rY = 18 + Math.random() * 4;
        this.conf      = Math.floor(93 + Math.random() * 6);
        this.blemish   = false;
      } else {
        this.category  = 'Large';
        this.sizeName  = '>75mm';
        this.rX = 30 + Math.random() * 6;
        this.rY = 23 + Math.random() * 5;
        this.conf      = Math.floor(94 + Math.random() * 6);
        this.blemish   = false;
      }

      this.rot        = Math.random() * Math.PI;
      this.scannedLogged = false;
      this.id         = `PT-${Math.floor(10493 + Math.random() * 89000)}`;
    }

    update(dx) {
      this.x += dx;
      if (this.x > cW + 70) this.reset(-55);
    }

    draw() {
      ctx.save();
      ctx.translate(this.x, this.y);
      ctx.rotate(this.rot);

      ctx.beginPath();
      ctx.ellipse(0, 0, this.rX, this.rY, 0, 0, Math.PI * 2);

      const g = ctx.createRadialGradient(-this.rX * 0.3, -this.rY * 0.3, 2, 0, 0, this.rX);
      if (this.blemish) {
        g.addColorStop(0, '#A16207');
        g.addColorStop(0.7, '#713F12');
        g.addColorStop(1, '#451A03');
      } else {
        g.addColorStop(0, '#FDE047');
        g.addColorStop(0.5, '#EAB308');
        g.addColorStop(1, '#A16207');
      }
      ctx.fillStyle = g;
      ctx.fill();

      // Blemish spots
      ctx.fillStyle = this.blemish ? 'rgba(20,5,0,0.85)' : 'rgba(113,63,18,0.35)';
      ctx.beginPath();
      ctx.arc(this.rX * 0.2, this.rY * 0.1, this.blemish ? 5 : 2, 0, Math.PI * 2);
      ctx.arc(-this.rX * 0.3, -this.rY * 0.2, this.blemish ? 6 : 1.5, 0, Math.PI * 2);
      ctx.fill();

      ctx.restore();
    }
  }

  const potatoes = [
    new Potato(cW * 0.18),
    new Potato(cW * 0.52),
    new Potato(cW * 0.83)
  ];

  let beltOffset = 0;
  let scanY = 0, scanDir = 1;

  function animateCanvas() {
    ctx.clearRect(0, 0, cW, cH);

    const beltTop    = Math.round(cH * 0.22);
    const beltHeight = Math.round(cH * 0.56);

    // Belt background
    ctx.fillStyle = '#0A0F1C';
    ctx.fillRect(0, beltTop, cW, beltHeight);

    // Rails
    ctx.fillStyle = '#1E2D45';
    ctx.fillRect(0, beltTop - 5, cW, 5);
    ctx.fillRect(0, beltTop + beltHeight, cW, 5);

    // Moving belt stripes
    if (state.isRunning) beltOffset = (beltOffset + state.speed * 4) % 30;

    ctx.strokeStyle = 'rgba(30,45,70,0.6)';
    ctx.lineWidth   = 1.5;
    for (let x = -30 + beltOffset; x < cW + 30; x += 30) {
      ctx.beginPath();
      ctx.moveTo(x, beltTop);
      ctx.lineTo(x + 12, beltTop + beltHeight);
      ctx.stroke();
    }

    // Inspection zone
    const zoneX  = cW * 0.5;
    const zoneW  = 120;
    const zoneGrad = ctx.createLinearGradient(zoneX - zoneW / 2, 0, zoneX + zoneW / 2, 0);
    zoneGrad.addColorStop(0, 'rgba(6,182,212,0)');
    zoneGrad.addColorStop(0.5, 'rgba(6,182,212,0.1)');
    zoneGrad.addColorStop(1, 'rgba(6,182,212,0)');
    ctx.fillStyle = zoneGrad;
    ctx.fillRect(zoneX - zoneW / 2, beltTop, zoneW, beltHeight);

    // Laser scanline
    if (state.showScanlines && state.isRunning) {
      scanY += 1.6 * scanDir;
      if (scanY > beltHeight - 5) scanDir = -1;
      if (scanY < 5)              scanDir =  1;

      ctx.save();
      ctx.strokeStyle  = '#06B6D4';
      ctx.lineWidth    = 1.5;
      ctx.shadowColor  = '#06B6D4';
      ctx.shadowBlur   = 8;
      ctx.beginPath();
      ctx.moveTo(zoneX - zoneW / 2 + 8, beltTop + scanY);
      ctx.lineTo(zoneX + zoneW / 2 - 8, beltTop + scanY);
      ctx.stroke();
      ctx.restore();
    }

    // Crosshair
    ctx.strokeStyle = 'rgba(100,116,139,0.25)';
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.moveTo(zoneX, beltTop + 10);
    ctx.lineTo(zoneX, beltTop + beltHeight - 10);
    ctx.moveTo(zoneX - 20, cH * 0.5);
    ctx.lineTo(zoneX + 20, cH * 0.5);
    ctx.stroke();

    // Potatoes
    const dx = state.isRunning ? state.speed * 4 : 0;
    let target = null;

    potatoes.forEach(p => {
      p.update(dx);
      p.draw();
      const inZone = Math.abs(p.x - zoneX) < zoneW / 2;
      if (inZone) {
        target = p;
        if (!p.scannedLogged && state.isRunning) {
          p.scannedLogged = true;
          handleDetected(p);
        }
      }
    });

    // Bounding box
    if (state.showBoxes && target) {
      drawBoundingBox(target);
      updateYoloPill(target);
    } else if (!target) {
      dom.yoloDetectionLabel.textContent = '[ Scanning field of view — no item in zone ]';
      dom.yoloConfPill.textContent       = 'READY';
      dom.yoloConfPill.style.color       = '#64748B';
    }

    requestAnimationFrame(animateCanvas);
  }

  function drawBoundingBox(p) {
    const isReject = p.category === 'Reject';
    const col      = isReject ? '#EF4444' : '#10B981';
    const fillCol  = isReject ? 'rgba(239,68,68,0.12)' : 'rgba(16,185,129,0.12)';
    const padX = 12, padY = 10;
    const bW = p.rX * 2 + padX;
    const bH = p.rY * 2 + padY;
    const bX = p.x - bW / 2;
    const bY = p.y - bH / 2;

    ctx.save();

    ctx.fillStyle = fillCol;
    ctx.fillRect(bX, bY, bW, bH);

    ctx.strokeStyle = col;
    ctx.lineWidth = 1.5;
    ctx.strokeRect(bX, bY, bW, bH);

    // Corner brackets
    const c = 9;
    ctx.lineWidth = 2.5;
    [
      [[bX, bY + c], [bX, bY], [bX + c, bY]],
      [[bX + bW - c, bY], [bX + bW, bY], [bX + bW, bY + c]],
      [[bX, bY + bH - c], [bX, bY + bH], [bX + c, bY + bH]],
      [[bX + bW - c, bY + bH], [bX + bW, bY + bH], [bX + bW, bY + bH - c]]
    ].forEach(pts => {
      ctx.beginPath();
      ctx.moveTo(...pts[0]);
      ctx.lineTo(...pts[1]);
      ctx.lineTo(...pts[2]);
      ctx.stroke();
    });

    // Label tag
    const tag   = `${isReject ? 'REJECT' : 'HEALTHY'} · ${p.category} · ${p.conf}%`;
    ctx.font    = 'bold 9px JetBrains Mono, monospace';
    const tw    = ctx.measureText(tag).width;
    const tagH  = 16;
    ctx.fillStyle = col;
    ctx.fillRect(bX, bY - tagH, tw + 12, tagH);
    ctx.fillStyle = '#fff';
    ctx.fillText(tag, bX + 6, bY - 4);

    ctx.restore();
  }

  function updateYoloPill(p) {
    const isReject = p.category === 'Reject';
    dom.yoloDetectionLabel.textContent = `[ Class: ${isReject ? 'Reject' : 'Healthy'} | Size: ${p.category} | Conf: ${p.conf}% ]`;
    dom.yoloConfPill.textContent = `${p.conf}% CONF`;
    dom.yoloConfPill.style.color = isReject ? '#EF4444' : '#34D399';
  }

  // =========================================================================
  // 5. DETECTION EVENT HANDLER
  // =========================================================================
  function handleDetected(p) {
    state.totalScanned += 1;
    state.bins[p.category.toLowerCase()] += 1;

    const actuatorMap = { Reject: 'Gate #1', Small: 'Chute #2', Medium: 'Chute #3', Large: 'Chute #4' };
    const now         = new Date();
    const ts          = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}.${String(now.getMilliseconds()).padStart(3,'0')}`;

    state.recentEvents.unshift({
      time: ts,
      id:   p.id,
      cls:  p.category === 'Reject' ? 'Reject' : 'Healthy',
      size: p.sizeName,
      conf: `${p.conf}%`,
      bin:  p.category,
      act:  actuatorMap[p.category]
    });
    if (state.recentEvents.length > 30) state.recentEvents.pop();

    updateDashboardUI();
    renderAuditTable();
  }

  // =========================================================================
  // 6. INTERVAL — Uptime + Telemetry
  // =========================================================================
  let uptimeSec = 9858;

  setInterval(() => {
    uptimeSec++;
    const h = String(Math.floor(uptimeSec / 3600)).padStart(2, '0');
    const m = String(Math.floor((uptimeSec % 3600) / 60)).padStart(2, '0');
    const s = String(uptimeSec % 60).padStart(2, '0');
    if (dom.uptimeDisplay) dom.uptimeDisplay.textContent = `${h}:${m}:${s}`;

    if (state.isRunning) {
      state.telemetry.temp        = (41.8 + Math.random() * 1.2).toFixed(1);
      state.telemetry.humidity    = Math.floor(63 + Math.random() * 5);
      state.telemetry.cpu         = Math.floor(26 + Math.random() * 8);
      state.telemetry.inferenceMs = (13.6 + Math.random() * 1.2).toFixed(1);
      state.telemetry.fps         = (29.5 + Math.random() * 0.6).toFixed(1);

      if (dom.metricSysTemp)    dom.metricSysTemp.textContent    = `${state.telemetry.temp}°C`;
      if (dom.metricHumidity)   dom.metricHumidity.textContent   = `${state.telemetry.humidity}%`;
      if (dom.metricCpuLoad)    dom.metricCpuLoad.textContent    = `${state.telemetry.cpu}%`;
      if (dom.inferenceLatency) dom.inferenceLatency.textContent = `${state.telemetry.inferenceMs} ms`;
      if (dom.camFps)           dom.camFps.textContent           = state.telemetry.fps;
    }
  }, 1000);

  // =========================================================================
  // 7. CONTROLS
  // =========================================================================
  dom.btnStartConveyor.addEventListener('click', () => {
    if (state.isRunning) { showToast('Conveyor already running', 'info'); return; }
    state.isRunning = true;
    state.speed     = 0.40;
    dom.systemStatusPill.className      = 'blocky-status active';
    dom.statusPillText.textContent       = 'ACTIVE';
    dom.liveBadgeIndicator.className     = 'live-badge';
    if (dom.speedStatusText) dom.speedStatusText.textContent = 'VFD Active';
    updateDashboardUI();
    showToast('Conveyor started — 0.40 m/s', 'success');
  });

  dom.btnStopConveyor.addEventListener('click', () => {
    if (!state.isRunning) { showToast('Conveyor already stopped', 'info'); return; }
    state.isRunning = false;
    state.speed     = 0.00;
    dom.systemStatusPill.className      = 'blocky-status';
    dom.statusPillText.textContent       = 'PAUSED';
    dom.liveBadgeIndicator.className     = 'live-badge live-inactive';
    if (dom.speedStatusText) dom.speedStatusText.textContent = 'Motor Halted';
    updateDashboardUI();
    showToast('Conveyor halted', 'warning');
  });

  dom.btnResetCounters.addEventListener('click', () => {
    dom.resetModal.classList.add('modal-open');
  });

  dom.btnCancelReset.addEventListener('click', () => {
    dom.resetModal.classList.remove('modal-open');
  });

  dom.btnConfirmReset.addEventListener('click', () => {
    state.totalScanned    = 0;
    state.bins.reject     = 0;
    state.bins.small      = 0;
    state.bins.medium     = 0;
    state.bins.large      = 0;
    state.recentEvents    = [];
    updateDashboardUI();
    renderAuditTable();
    dom.resetModal.classList.remove('modal-open');
    showToast('Batch counters reset to 0', 'info');
  });

  dom.resetModal.addEventListener('click', e => {
    if (e.target === dom.resetModal) dom.resetModal.classList.remove('modal-open');
  });

  if (dom.btnExportCsv) {
    dom.btnExportCsv.addEventListener('click', () => {
      const headers = ['Timestamp','Item_ID','Classification','Size_Grade','Confidence','Assigned_Bin','Actuator_Triggered'];
      const rows = state.recentEvents.map(e => [
        `"${e.time}"`, `"${e.id}"`, `"${e.cls}"`,
        `"${e.size}"`, `"${e.conf}"`, `"${e.bin}"`, `"${e.act}"`
      ]);
      if (!rows.length) rows.push([`"${new Date().toISOString()}"`,'"BATCH-SUMMARY"',`"Total:${state.totalScanned}"`,`"Healthy:${state.bins.small+state.bins.medium+state.bins.large}"`,`"Ratio:${Math.round((state.bins.small+state.bins.medium+state.bins.large)/Math.max(state.totalScanned,1)*100)}%"`,`"Reject:${state.bins.reject}"`,'"Complete"']);
      const csv = 'data:text/csv;charset=utf-8,' + headers.join(',') + '\n' + rows.map(r => r.join(',')).join('\n');
      const link = document.createElement('a');
      link.href = encodeURI(csv);
      link.download = `potato_log_${new Date().toISOString().slice(0,10)}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      showToast('CSV exported', 'success');
    });
  }

  dom.chkShowBoxes.addEventListener('change',       e => { state.showBoxes       = e.target.checked; });
  dom.chkShowScanlines.addEventListener('change',   e => { state.showScanlines   = e.target.checked; });
  dom.chkSimulateDefects.addEventListener('change', e => { state.simulateDefects = e.target.checked; });

  // =========================================================================
  // 8. INIT
  // =========================================================================
  updateDashboardUI();
  renderAuditTable();
  requestAnimationFrame(animateCanvas);
  showToast('Station #01 Online — Ready', 'success');

})();
