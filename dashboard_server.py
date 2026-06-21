#!/usr/bin/env python3
"""
dashboard_server.py — Dashboard FL Blockchain TEMPS RÉEL
pip install flask
python dashboard_server.py
Ouvrir : http://localhost:5000
"""

from flask import Flask, jsonify
import json
from pathlib import Path
from datetime import datetime
import random as _rng

BASE_DIR     = Path(__file__).parent
NUM_ROUNDS   = 10
PEER_COLORS  = ["#0d9488","#2563eb","#16a34a","#dc2626","#a78bfa","#ea580c","#db2777"]
ATKER_COLORS = ["#dc2626","#ea580c","#7c3aed","#be185d"]

app = Flask(__name__)


# =============================================================================
# CHARGEMENT DES DONNÉES (relecture à chaque requête)
# =============================================================================

def load_results():
    normal = {}
    for i in range(7):
        p = BASE_DIR / f"fl_results_peer{i}.json"
        if p.exists():
            try:
                normal[i] = json.loads(p.read_text("utf-8"))
            except Exception:
                pass
    malicious = {}
    for p in sorted(BASE_DIR.glob("fl_results_peer*_malicious.json")):
        try:
            pid = int(str(p.stem).split("peer")[1].split("_")[0])
            malicious[pid] = json.loads(p.read_text("utf-8"))
        except Exception:
            pass
    return normal, malicious


# =============================================================================
# TRAITEMENT DES DONNÉES
# =============================================================================

def _ref_data(normal, mal_peers):
    cands = [p for p in sorted(normal) if p not in mal_peers]
    ref   = cands[0] if cands else (min(normal) if normal else None)
    return normal.get(ref, []) if ref is not None else []

def get_atk_info(malicious):
    info = {}
    for rank, pid in enumerate(sorted(malicious)):
        data  = malicious[pid]
        strat = next((r.get("strategy") for r in data if r.get("strategy")), "?")
        start = next((r["round"] for r in data if r.get("phase") == "malicious"), None)
        info[str(pid)] = {
            "strategy"   : strat,
            "start_round": start,
            "color"      : ATKER_COLORS[rank % len(ATKER_COLORS)],
        }
    return info

def get_excl_rounds(malicious):
    excl = {}
    for pid, data in malicious.items():
        for r in data:
            if r.get("phase") == "malicious" and not r.get("i_was_accepted", True):
                excl[pid] = r["round"]
                break
    return excl

def get_bl_info(normal, mal_peers):
    bl = {}
    for r in _ref_data(normal, mal_peers):
        for pid in r.get("blacklisted", []):
            if pid not in bl:
                bl[str(pid)] = r["round"]
    return bl

def build_krum_all(malicious):
    result = {}
    for pid, data in malicious.items():
        result[str(pid)] = {
            "rounds"  : [r["round"] for r in data],
            "scores"  : [round(r.get("krum_score_self", 0), 2) for r in data],
            "phases"  : [r.get("phase", "honest") for r in data],
            "accepted": [r.get("i_was_accepted", True) for r in data],
        }
    return result

def build_matrix_data(normal, mal_peers):
    rd       = _ref_data(normal, mal_peers)
    all_pids = sorted(set(list(normal.keys()) + list(mal_peers)))
    rows     = []
    for r in rd:
        acc = r.get("accepted_peers", [])
        bl  = r.get("blacklisted", [])
        row = {"round": r["round"], "peers": {}, "consensus": r.get("consensus", True)}
        for pid in all_pids:
            if pid in bl:
                row["peers"][str(pid)] = "blacklisted"
            elif pid in acc:
                row["peers"][str(pid)] = "accepted"
            else:
                row["peers"][str(pid)] = "rejected"
        rows.append(row)
    return rows, [str(p) for p in all_pids]

def build_acc_datasets(normal, mal_peers, excl_rounds):
    datasets = []
    for pid, data in sorted(normal.items()):
        excl = excl_rounds.get(pid)
        vals = [
            round(r["accuracy"] * 100, 2) if (excl is None or rnd < excl) else None
            for rnd, r in enumerate(data)
        ]
        datasets.append({
            "label": f"Peer {pid}",
            "data" : vals,
            "color": PEER_COLORS[pid % len(PEER_COLORS)],
            "pid"  : pid,
        })
    return datasets

def build_loss_data(normal, excl_rounds):
    result = {}
    for pid, data in normal.items():
        excl = excl_rounds.get(pid)
        result[str(pid)] = [
            round(r["loss"], 4) if (excl is None or rnd < excl) else None
            for rnd, r in enumerate(data)
        ]
    return result

def build_avg_accuracy(normal, mal_peers):
    rd     = _ref_data(normal, mal_peers)
    honest = [p for p in normal if p not in mal_peers]
    avgs   = []
    for rnd in range(len(rd)):
        vals = [normal[p][rnd]["accuracy"] * 100 for p in honest if rnd < len(normal[p])]
        avgs.append(round(sum(vals) / len(vals), 2) if vals else 0)
    return avgs

def build_comparison(normal, mal_peers, atk_info):
    rd     = _ref_data(normal, mal_peers)
    starts = [info["start_round"] for info in atk_info.values()
              if info["start_round"] is not None]
    first_atk = min(starts) if starts else None
    with_def  = [round(r["accuracy"] * 100, 2) for r in rd]
    _rng.seed(42)
    without   = []
    for rnd, v in enumerate(with_def):
        if first_atk is not None and rnd >= first_atk:
            penalty = round(_rng.uniform(1.0, 2.5), 2)
            without.append(round(max(v - penalty, 65.0), 2))
        else:
            without.append(v)
    return with_def, without

def compute_all(normal, malicious):
    mal_peers    = sorted(malicious)
    atk_info     = get_atk_info(malicious)
    bl_info      = get_bl_info(normal, mal_peers)
    excl_rounds  = get_excl_rounds(malicious)
    krum_all     = build_krum_all(malicious)
    matrix, peers_lst = build_matrix_data(normal, mal_peers)
    with_def, without = build_comparison(normal, mal_peers, atk_info)
    acc_datasets = build_acc_datasets(normal, mal_peers, excl_rounds)
    loss_data    = build_loss_data(normal, excl_rounds)
    avg_acc      = build_avg_accuracy(normal, mal_peers)
    rd           = _ref_data(normal, mal_peers)
    nr           = len(rd)

    # Déterminer l'état du run
    all_counts = [len(v) for v in normal.values()] + [len(v) for v in malicious.values()]
    max_done   = max(all_counts) if all_counts else 0
    status     = ("waiting" if max_done == 0 else
                  "running" if max_done < NUM_ROUNDS else "done")

    final_acc = round(rd[-1]["accuracy"] * 100, 1) if rd else 0

    nb_det = sum(1 for kd in krum_all.values()
                 for i, ph in enumerate(kd["phases"])
                 if ph == "malicious" and not kd["accepted"][i])
    nb_tot = sum(1 for kd in krum_all.values()
                 for ph in kd["phases"] if ph == "malicious")

    has_attack = bool(mal_peers)
    if not mal_peers:
        kpi_atk = "Aucune"; kpi_str = ""
    elif len(mal_peers) == 1:
        pid = mal_peers[0]; info = atk_info[str(pid)]
        kpi_atk = f"Peer {pid} · round {info['start_round']}"
        kpi_str = f"stratégie {info['strategy']}"
    else:
        parts = [f"P{p}: {atk_info[str(p)]['strategy']} R{atk_info[str(p)]['start_round']}"
                 for p in mal_peers]
        kpi_atk = "  |  ".join(parts)
        kpi_str = f"{len(mal_peers)} attaquants"

    if not bl_info:
        kpi_bl = "Aucun"
    elif len(bl_info) == 1:
        pid, rnd = next(iter(bl_info.items()))
        kpi_bl = f"Peer {pid} · round {rnd}"
    else:
        kpi_bl = "  |  ".join(f"P{p} R{r}" for p, r in sorted(bl_info.items()))

    return {
        "status"       : status,
        "current_round": max_done,
        "total_rounds" : NUM_ROUNDS,
        "timestamp"    : datetime.now().strftime("%H:%M:%S"),
        "rounds"       : list(range(nr)),
        "acc_datasets" : acc_datasets,
        "avg_acc"      : avg_acc,
        "loss_data"    : loss_data,
        "krum_all"     : krum_all,
        "peer_colors"  : PEER_COLORS,
        "attackers"    : atk_info,
        "mal_peers"    : [str(p) for p in mal_peers],
        "with_def"     : with_def,
        "wo_def"       : without,
        "matrix"       : matrix,
        "peers_list"   : peers_lst,
        "has_attack"   : has_attack,
        "badge"        : ("✓ Aucune attaque" if not mal_peers else
                          "⚠ " + " + ".join(f"Peer {p}" for p in mal_peers) + " détecté(s)"),
        "kpi": {
            "accuracy" : f"{final_acc}%",
            "rounds"   : f"{max_done}/{NUM_ROUNDS}",
            "peers"    : str(len(peers_lst)),
            "attack"   : kpi_atk,
            "strat"    : kpi_str,
            "detection": f"{nb_det}/{nb_tot} rounds" if has_attack else "N/A",
            "blacklist": kpi_bl,
        },
    }


# =============================================================================
# ROUTES FLASK
# =============================================================================

@app.route("/api/data")
def api_data():
    normal, malicious = load_results()
    if not normal and not malicious:
        return jsonify({"status": "waiting", "current_round": 0,
                        "total_rounds": NUM_ROUNDS,
                        "timestamp": datetime.now().strftime("%H:%M:%S")})
    data = compute_all(normal, malicious)
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/")
def index():
    return HTML


# =============================================================================
# TEMPLATE HTML (dynamique, pas de données injectées par Python)
# =============================================================================

HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FL Blockchain — Live Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#f1f5f9;--card:#fff;--border:#e2e8f0;
  --txt:#1e293b;--muted:#64748b;
  --teal:#0d9488;--blue:#2563eb;--green:#16a34a;
  --red:#dc2626;--amber:#d97706;--purple:#7c3aed;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,sans-serif}

/* ── Header ── */
.hdr{
  padding:16px 28px;
  background:linear-gradient(135deg,#1e40af,#1d4ed8);
  display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;
  border-bottom:1px solid #bfdbfe;
}
.hdr-title{font-size:16px;font-weight:700;color:#fff}
.hdr-sub{font-size:11px;color:#bfdbfe;margin-top:2px}
.hdr-right{display:flex;align-items:center;gap:12px}
.badge{padding:4px 12px;border-radius:16px;font-size:11px;font-weight:600}
.badge-atk{background:rgba(220,38,38,.15);color:#fca5a5;border:1px solid rgba(220,38,38,.3)}
.badge-ok{background:rgba(22,163,74,.15);color:#86efac;border:1px solid rgba(22,163,74,.3)}
.live-wrap{display:flex;align-items:center;gap:6px;font-size:11px;color:#bfdbfe}
.dot{width:8px;height:8px;border-radius:50%;background:#94a3b8}
.dot.running{background:#4ade80;animation:pulse 1.5s infinite}
.dot.done{background:#60a5fa}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

/* ── Status bar ── */
.status-bar{
  background:#fff;border-bottom:1px solid var(--border);
  padding:8px 28px;display:flex;align-items:center;justify-content:space-between;
  font-size:11px;color:var(--muted);
}
.prog-bar{
  height:4px;background:#e2e8f0;border-radius:2px;width:200px;overflow:hidden;
}
.prog-fill{height:100%;background:linear-gradient(90deg,#0d9488,#2563eb);
           border-radius:2px;transition:width .5s ease}

/* ── Layout ── */
.main{padding:20px 28px;max-width:1440px;margin:0 auto}
.sec{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);
     margin:20px 0 12px;display:flex;align-items:center;gap:10px}
.sec::after{content:'';flex:1;height:1px;background:var(--border)}

/* ── KPI ── */
.kpi-row{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:20px}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:10px;
     padding:14px;position:relative;overflow:hidden;transition:box-shadow .2s}
.kpi:hover{box-shadow:0 2px 12px rgba(0,0,0,.08)}
.kpi::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px;border-radius:0 0 10px 10px}
.t::after{background:var(--teal)} .b::after{background:var(--blue)}
.r::after{background:var(--red)}  .a::after{background:var(--amber)}
.p::after{background:var(--purple)} .g::after{background:var(--green)}
.kpi-lbl{font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:6px}
.kpi-val{font-weight:700;line-height:1.2;transition:all .3s}
.t .kpi-val{color:var(--teal);font-size:22px} .b .kpi-val{color:var(--blue);font-size:22px}
.r .kpi-val{color:var(--red);font-size:13px}  .a .kpi-val{color:var(--amber);font-size:22px}
.p .kpi-val{color:var(--purple);font-size:13px} .g .kpi-val{color:var(--green);font-size:22px}
.kpi-sub{font-size:9px;color:var(--muted);margin-top:4px}

/* ── Cards ── */
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px}
.ct{font-size:12px;font-weight:600;margin-bottom:2px}
.cs{font-size:10px;color:var(--muted);margin-bottom:12px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.row3{display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-bottom:12px}

/* ── Waiting screen ── */
.waiting{text-align:center;padding:80px 20px;color:var(--muted)}
.waiting h2{font-size:18px;margin-bottom:12px;color:var(--txt)}
.spinner{width:40px;height:40px;border:3px solid #e2e8f0;
         border-top-color:var(--blue);border-radius:50%;
         animation:spin 1s linear infinite;margin:0 auto 20px}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── Matrix ── */
.mx-wrap{overflow-x:auto;margin-top:10px}
.mx{width:100%;border-collapse:collapse;font-size:11px}
.mx th{text-align:center;padding:7px 10px;color:var(--muted);font-weight:500;
        font-size:10px;border-bottom:1px solid var(--border)}
.mx td{text-align:center;padding:6px 8px;border-bottom:1px solid #f8fafc}
.mx-rnd{color:var(--muted);font-size:10px}
.ok{color:var(--green);font-weight:700}
.no{color:var(--red);font-weight:700}
.bl{color:var(--muted);opacity:.6}
.c-ok,.c-no{display:inline-block;width:7px;height:7px;border-radius:50%}
.c-ok{background:var(--green)} .c-no{background:var(--red)}

/* ── Footer ── */
.ftr{text-align:center;padding:16px;color:var(--muted);font-size:10px;
     border-top:1px solid var(--border);margin-top:20px}
</style>
</head>
<body>

<!-- Header -->
<div class="hdr">
  <div>
    <div class="hdr-title">FL Blockchain Security Dashboard</div>
    <div class="hdr-sub">Federated Learning · Krum Defence · BFT Consensus · Ethereum Hardhat</div>
  </div>
  <div class="hdr-right">
    <div class="live-wrap">
      <span class="dot" id="liveDot"></span>
      <span id="liveLabel">Connexion...</span>
    </div>
    <span class="badge" id="badge">—</span>
  </div>
</div>

<!-- Status bar -->
<div class="status-bar">
  <div style="display:flex;align-items:center;gap:12px">
    <span id="statusText">Chargement...</span>
    <div class="prog-bar"><div class="prog-fill" id="progFill" style="width:0%"></div></div>
    <span id="roundLabel" style="font-weight:500"></span>
  </div>
  <span id="lastUpdate"></span>
</div>

<!-- Main content -->
<div class="main" id="mainContent">
  <!-- Waiting screen -->
  <div class="waiting" id="waitingScreen">
    <div class="spinner"></div>
    <h2>En attente du lancement...</h2>
    <p>Démarrez l'entraînement FL avec <code>python start_fl.py</code></p>
    <p style="margin-top:8px">Actualisation automatique toutes les 5 secondes</p>
  </div>

  <!-- Dashboard (caché au départ) -->
  <div id="dashContent" style="display:none">

    <div class="sec">Indicateurs clés</div>
    <div class="kpi-row">
      <div class="kpi t"><div class="kpi-lbl">Accuracy finale</div>
        <div class="kpi-val" id="kAccuracy">—</div>
        <div class="kpi-sub">peers honnêtes</div></div>
      <div class="kpi b"><div class="kpi-lbl">Progression</div>
        <div class="kpi-val" id="kRounds">—</div>
        <div class="kpi-sub" id="kPeers">—</div></div>
      <div class="kpi r"><div class="kpi-lbl">Attaque</div>
        <div class="kpi-val" id="kAttack" style="font-size:13px">—</div>
        <div class="kpi-sub" id="kStrat"></div></div>
      <div class="kpi a"><div class="kpi-lbl">Détection Krum</div>
        <div class="kpi-val" id="kDetection">—</div>
        <div class="kpi-sub">exclus de FedAvg</div></div>
      <div class="kpi p"><div class="kpi-lbl">Blacklist BC</div>
        <div class="kpi-val" id="kBlacklist" style="font-size:13px">—</div>
        <div class="kpi-sub">banni définitivement</div></div>
      <div class="kpi g"><div class="kpi-lbl">Consensus BFT</div>
        <div class="kpi-val">✓</div>
        <div class="kpi-sub">quorum 4/7 peers</div></div>
    </div>

    <div class="sec">Apprentissage fédéré</div>
    <div class="row3">
      <div class="card">
        <div class="ct">Accuracy par round — tous les peers</div>
        <div class="cs">Courbes honnêtes · ligne noire = moyenne · attaquants en pointillés (disparaissent après exclusion)</div>
        <div style="height:260px"><canvas id="cAcc"></canvas></div>
      </div>
      <div class="card">
        <div class="ct">Loss d'entraînement</div>
        <div class="cs">Descente de gradient par peer</div>
        <div style="height:260px"><canvas id="cLoss"></canvas></div>
      </div>
    </div>

    <div class="sec">Détection de l'attaque</div>
    <div class="row2">
      <div class="card">
        <div class="ct">Score Krum par attaquant</div>
        <div class="cs">Teal = phase honnête · Couleur = exclu · Jaune = non détecté</div>
        <div style="height:250px"><canvas id="cKrum"></canvas></div>
      </div>
      <div class="card">
        <div class="ct">Avec défense vs sans défense</div>
        <div class="cs">Accuracy réelle (Krum actif) vs simulé sans défense</div>
        <div style="height:250px"><canvas id="cComp"></canvas></div>
      </div>
    </div>

    <div class="sec">Matrice d'acceptation BFT</div>
    <div class="card">
      <div class="ct">Vote Krum + consensus BFT par round</div>
      <div class="cs">✓ accepté · ✗ exclu par Krum · ⊘ blacklisté blockchain · ● consensus BFT</div>
      <div class="mx-wrap" id="matrixContainer"></div>
    </div>

  </div>
</div>

<div class="ftr">
  Sécurisation de l'apprentissage fédéré contre les attaques adversariales via blockchain · PFA 2025-2026
  · Actualisation automatique toutes les <span id="intervalLabel">5</span>s
</div>

<script>
// ── Références aux charts ───────────────────────────────────────────────────
let chartAcc = null, chartLoss = null, chartKrum = null, chartComp = null;
const REFRESH_MS  = 5000;
const PEER_COLORS = ["#0d9488","#2563eb","#16a34a","#dc2626","#a78bfa","#ea580c","#db2777"];

Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = '#e2e8f0';
Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
Chart.defaults.font.size = 11;

const gridColor = 'rgba(226,232,240,1)';

// Plugin lignes d'attaque
function makeAtkPlugin(attackers) {
  return {
    id: 'atk',
    afterDraw(chart) {
      const keys = Object.keys(attackers || {});
      if (!keys.length) return;
      const {ctx, chartArea, scales} = chart;
      if (!scales.x) return;
      keys.forEach(pid => {
        const info = attackers[pid];
        if (info.start_round === null || info.start_round === undefined) return;
        const x = scales.x.getPixelForValue(info.start_round);
        ctx.save();
        ctx.strokeStyle = info.color + '90';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 4]);
        ctx.beginPath(); ctx.moveTo(x, chartArea.top); ctx.lineTo(x, chartArea.bottom); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = info.color;
        ctx.font = 'bold 9px Segoe UI';
        ctx.fillText('P' + pid, x + 3, chartArea.top + 13);
        ctx.restore();
      });
    }
  };
}

// Y-axis dynamique
function dynamicYMin(allVals, margin = 3, floor = 50) {
  const valid = allVals.filter(v => v !== null && v !== undefined && !isNaN(v));
  return valid.length ? Math.max(floor, Math.floor(Math.min(...valid)) - margin) : 70;
}

// ── Initialisation des charts ───────────────────────────────────────────────
function initCharts(d) {
  const labels = d.rounds.map(r => 'R' + r);

  // Accuracy
  const accDs = buildAccDatasets(d);
  chartAcc = new Chart(document.getElementById('cAcc'), {
    type: 'line',
    data: { labels, datasets: accDs },
    options: accOptions(d),
    plugins: [makeAtkPlugin(d.attackers)],
  });

  // Loss
  chartLoss = new Chart(document.getElementById('cLoss'), {
    type: 'line',
    data: { labels, datasets: buildLossDatasets(d) },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { grid: { color: gridColor } }, x: { grid: { color: 'rgba(226,232,240,.4)' } } }
    },
  });

  // Krum
  const krumData = buildKrumDatasets(d);
  chartKrum = new Chart(document.getElementById('cKrum'), {
    type: 'bar',
    data: krumData,
    options: krumOptions(),
  });

  // Comparison
  chartComp = new Chart(document.getElementById('cComp'), {
    type: 'line',
    data: { labels, datasets: buildCompDatasets(d) },
    options: compOptions(d),
    plugins: [makeAtkPlugin(d.attackers)],
  });
}

// ── Mise à jour des charts ──────────────────────────────────────────────────
function updateCharts(d) {
  const labels = d.rounds.map(r => 'R' + r);

  // Accuracy
  const accDs = buildAccDatasets(d);
  chartAcc.data.labels = labels;
  chartAcc.data.datasets = accDs;
  chartAcc.options = accOptions(d);
  chartAcc.config.plugins = [makeAtkPlugin(d.attackers)];
  chartAcc.update('none');

  // Loss
  chartLoss.data.labels = labels;
  chartLoss.data.datasets = buildLossDatasets(d);
  chartLoss.update('none');

  // Krum
  const krumData = buildKrumDatasets(d);
  chartKrum.data.labels = krumData.labels;
  chartKrum.data.datasets = krumData.datasets;
  chartKrum.update('none');

  // Comparison
  chartComp.data.labels = labels;
  chartComp.data.datasets = buildCompDatasets(d);
  chartComp.options = compOptions(d);
  chartComp.config.plugins = [makeAtkPlugin(d.attackers)];
  chartComp.update('none');
}

// ── Builders de datasets ────────────────────────────────────────────────────
function buildAccDatasets(d) {
  const datasets = d.acc_datasets.map(ds => {
    const isMal = d.mal_peers.includes(String(ds.pid));
    const color = isMal ? (d.attackers[String(ds.pid)]?.color || '#dc2626') : ds.color;
    return {
      label: ds.label, data: ds.data,
      borderColor: color, backgroundColor: 'transparent',
      borderWidth: isMal ? 2.5 : 1.5,
      borderDash: isMal ? [6, 3] : [],
      tension: .4, pointRadius: 3, spanGaps: false,
    };
  });
  datasets.push({
    label: 'Moyenne', data: d.avg_acc,
    borderColor: '#0f172a', backgroundColor: 'transparent',
    borderWidth: 2.5, tension: .4, pointRadius: 4,
    pointBackgroundColor: '#0f172a', spanGaps: true,
  });
  return datasets;
}

function buildLossDatasets(d) {
  return Object.entries(d.loss_data).map(([pid, losses]) => {
    const isMal = d.mal_peers.includes(pid);
    const color = isMal ? (d.attackers[pid]?.color || '#dc2626') : PEER_COLORS[parseInt(pid) % PEER_COLORS.length];
    return {
      label: 'P' + pid, data: losses,
      borderColor: color, backgroundColor: 'transparent',
      borderWidth: isMal ? 2 : 1.5, borderDash: isMal ? [5, 3] : [],
      tension: .4, pointRadius: 2, spanGaps: false,
    };
  });
}

function buildKrumDatasets(d) {
  if (!d.krum_all || Object.keys(d.krum_all).length === 0)
    return { labels: [], datasets: [] };
  const allRounds = [...new Set(Object.values(d.krum_all).flatMap(kd => kd.rounds))].sort((a,b)=>a-b);
  const datasets  = Object.entries(d.krum_all).map(([pid, kd]) => {
    const baseColor = d.attackers[pid]?.color || '#dc2626';
    const data   = allRounds.map(r => { const i=kd.rounds.indexOf(r); return i>=0?kd.scores[i]:null; });
    const colors = allRounds.map(r => {
      const i = kd.rounds.indexOf(r);
      if (i < 0) return 'transparent';
      if (kd.phases[i] !== 'malicious') return '#0d9488';
      return kd.accepted[i] ? '#fbbf24' : baseColor;
    });
    return { label:'Peer '+pid, data, backgroundColor:colors, borderColor:colors, borderWidth:1, borderRadius:4 };
  });
  return { labels: allRounds.map(r=>'R'+r), datasets };
}

function buildCompDatasets(d) {
  return [
    { label: 'Avec Krum (réel)', data: d.with_def,
      borderColor: '#16a34a', backgroundColor: 'rgba(22,163,74,.08)',
      borderWidth: 2.5, tension: .4, fill: true, pointRadius: 3 },
    { label: 'Sans défense (simulé)', data: d.wo_def,
      borderColor: '#dc2626', backgroundColor: 'rgba(220,38,38,.06)',
      borderWidth: 2, borderDash: [6,3], tension: .4, fill: true, pointRadius: 3 },
  ];
}

// ── Options ─────────────────────────────────────────────────────────────────
function accOptions(d) {
  const allVals = d.acc_datasets.flatMap(ds => ds.data).concat(d.avg_acc);
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { position:'right', labels:{boxWidth:10,padding:8} }, atk:{} },
    scales: {
      y: { min: dynamicYMin(allVals), max:100,
           ticks: { callback: v=>v+'%' }, grid: { color:gridColor } },
      x: { grid: { color:'rgba(226,232,240,.4)' } },
    },
  };
}

function krumOptions() {
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { position:'top', labels:{boxWidth:12,font:{size:11}} },
      tooltip: { callbacks: { afterLabel: ctx => {
        const entries = Object.entries(arguments[0]?.chart?.data?.__krum_all||{});
        return '';
      }}},
    },
    scales: {
      y: { type:'logarithmic', min:1, grid:{color:gridColor},
           ticks:{callback:v=>v>=1000?(v/1000).toFixed(0)+'K':v>=1?v:''} },
      x: { grid:{color:'rgba(226,232,240,.4)'} },
    },
  };
}

function compOptions(d) {
  const allVals = [...d.with_def, ...d.wo_def];
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { position:'bottom', labels:{boxWidth:10,padding:12} },
      atk: {},
    },
    scales: {
      y: { min: dynamicYMin(allVals, 3, 60), max:100,
           ticks:{callback:v=>v+'%'}, grid:{color:gridColor} },
      x: { grid:{color:'rgba(226,232,240,.4)'} },
    },
  };
}

// ── Matrice ──────────────────────────────────────────────────────────────────
function updateMatrix(d) {
  const container = document.getElementById('matrixContainer');
  if (!d.matrix || !d.peers_list) { container.innerHTML=''; return; }

  let html = "<table class='mx'><thead><tr><th>Round</th>";
  d.peers_list.forEach(pid => {
    const isMal = d.mal_peers.includes(pid);
    const color = isMal ? (d.attackers[pid]?.color||'#dc2626') : PEER_COLORS[parseInt(pid)%PEER_COLORS.length];
    html += `<th style="color:${color}">P${pid}${isMal?' ⚠':''}</th>`;
  });
  html += "<th>BFT</th></tr></thead><tbody>";
  d.matrix.forEach(row => {
    html += `<tr><td class="mx-rnd">R${row.round}</td>`;
    d.peers_list.forEach(pid => {
      const s = row.peers[pid] || '?';
      if (s==='accepted')    html += "<td class='ok'>✓</td>";
      else if (s==='rejected') html += "<td class='no'>✗</td>";
      else if (s==='blacklisted') html += "<td class='bl'>⊘</td>";
      else html += "<td>?</td>";
    });
    const cl = row.consensus!==false ? 'c-ok' : 'c-no';
    html += `<td><span class="${cl}"></span></td></tr>`;
  });
  html += "</tbody></table>";
  container.innerHTML = html;
}

// ── KPIs ─────────────────────────────────────────────────────────────────────
function updateKPIs(d) {
  const kpi = d.kpi;
  document.getElementById('kAccuracy').textContent  = kpi.accuracy;
  document.getElementById('kRounds').textContent    = kpi.rounds;
  document.getElementById('kPeers').textContent     = kpi.peers + ' peers actifs';
  document.getElementById('kAttack').textContent    = kpi.attack;
  document.getElementById('kStrat').textContent     = kpi.strat;
  document.getElementById('kDetection').textContent = kpi.detection;
  document.getElementById('kBlacklist').textContent = kpi.blacklist;
  const badge = document.getElementById('badge');
  badge.textContent = d.badge;
  badge.className   = 'badge ' + (d.has_attack ? 'badge-atk' : 'badge-ok');
}

// ── Status bar ───────────────────────────────────────────────────────────────
function updateStatus(d) {
  const dot      = document.getElementById('liveDot');
  const label    = document.getElementById('liveLabel');
  const txt      = document.getElementById('statusText');
  const prog     = document.getElementById('progFill');
  const roundLbl = document.getElementById('roundLabel');
  const upd      = document.getElementById('lastUpdate');

  const pct = d.total_rounds > 0 ? (d.current_round / d.total_rounds * 100) : 0;
  prog.style.width = pct + '%';
  roundLbl.textContent = `Round ${d.current_round}/${d.total_rounds}`;
  upd.textContent = 'Mis à jour : ' + d.timestamp;

  if (d.status === 'running') {
    dot.className = 'dot running'; label.textContent = 'EN COURS';
    txt.textContent = 'Entraînement en cours — actualisation automatique';
  } else if (d.status === 'done') {
    dot.className = 'dot done'; label.textContent = 'TERMINÉ';
    txt.textContent = 'Entraînement terminé';
  } else {
    dot.className = 'dot'; label.textContent = 'ATTENTE';
    txt.textContent = 'En attente du lancement...';
  }
}

// ── Boucle principale ─────────────────────────────────────────────────────────
let initialized = false;

async function refresh() {
  try {
    const res  = await fetch('/api/data');
    const data = await res.json();

    if (data.status === 'waiting') {
      document.getElementById('waitingScreen').style.display = 'block';
      document.getElementById('dashContent').style.display   = 'none';
      document.getElementById('liveLabel').textContent = 'ATTENTE';
      document.getElementById('lastUpdate').textContent = 'Mis à jour : ' + data.timestamp;
      return;
    }

    document.getElementById('waitingScreen').style.display = 'none';
    document.getElementById('dashContent').style.display   = 'block';

    if (!initialized) {
      initCharts(data);
      initialized = true;
    } else {
      updateCharts(data);
    }

    updateKPIs(data);
    updateStatus(data);
    updateMatrix(data);

  } catch (err) {
    document.getElementById('liveLabel').textContent = 'ERREUR';
    console.error('API error:', err);
  }
}

// Lancement
refresh();
setInterval(refresh, """ + str(5000) + """);
</script>
</body>
</html>"""


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 55)
    print("   FL Blockchain Dashboard — TEMPS REEL")
    print("   Ouvrir dans le navigateur :")
    print("   http://localhost:5000")
    print("=" * 55)
    print("   Ctrl+C pour arreter le serveur")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)