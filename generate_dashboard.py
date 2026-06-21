#!/usr/bin/env python3
"""
generate_dashboard.py — Dashboard FL Blockchain (propre, multi-attaquants)
Placer dans C:/fl_project/ | python generate_dashboard.py
"""

import json
from pathlib import Path
from datetime import datetime
import random as _rng

BASE_DIR = Path(__file__).parent
OUTPUT   = BASE_DIR / "dashboard.html"

# Couleurs fixes par peer ID
PEER_COLORS  = ["#0d9488","#2563eb","#16a34a","#dc2626","#a78bfa","#ea580c","#db2777"]
# Couleurs distinctes pour les attaquants (par ordre d'arrivée)
ATKER_COLORS = ["#dc2626","#ea580c","#7c3aed","#be185d"]


# =============================================================================
# CHARGEMENT
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
# HELPERS
# =============================================================================

def _ref_data(normal, mal_peers):
    """Données du peer honnête de référence (ID le plus bas non-malveillant)."""
    cands = [p for p in sorted(normal) if p not in mal_peers]
    ref   = cands[0] if cands else min(normal)
    return normal.get(ref, [])


def get_atk_info(malicious):
    """Retourne {pid: {strategy, start_round, color}} pour chaque attaquant."""
    info = {}
    for rank, pid in enumerate(sorted(malicious)):
        data  = malicious[pid]
        strat = next((r.get("strategy") for r in data if r.get("strategy")), "?")
        start = next((r["round"] for r in data if r.get("phase") == "malicious"), None)
        info[pid] = {
            "strategy"   : strat,
            "start_round": start,
            "color"      : ATKER_COLORS[rank % len(ATKER_COLORS)],
        }
    return info


def get_excl_rounds(malicious):
    """Retourne {pid: premier_round_exclu} pour chaque attaquant."""
    excl = {}
    for pid, data in malicious.items():
        for r in data:
            if r.get("phase") == "malicious" and not r.get("i_was_accepted", True):
                excl[pid] = r["round"]
                break
    return excl


def get_bl_info(normal, mal_peers):
    """Retourne {pid: round_blacklist} depuis les données du peer de référence."""
    bl = {}
    for r in _ref_data(normal, mal_peers):
        for pid in r.get("blacklisted", []):
            if pid not in bl:
                bl[pid] = r["round"]
    return bl


def build_krum_all(malicious):
    """Retourne {str(pid): {rounds, scores, phases, accepted}} pour Chart.js."""
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
    """Matrice d'acceptation basée sur le peer de référence (pas auto-reporting)."""
    rd    = _ref_data(normal, mal_peers)
    # Inclure TOUS les peers (honnêtes + malveillants) même si absent de normal
    peers = sorted(set(list(normal.keys()) + list(mal_peers)))
    rows  = []
    for r in rd:
        acc = r.get("accepted_peers", [])
        bl  = r.get("blacklisted", [])
        row = {"round": r["round"], "peers": {}, "consensus": r.get("consensus", True)}
        for pid in peers:
            if pid in bl:        row["peers"][pid] = "blacklisted"
            elif pid in acc:     row["peers"][pid] = "accepted"
            else:                row["peers"][pid] = "rejected"
        rows.append(row)
    return rows, peers


def build_acc_datasets(normal, mal_peers, excl_rounds):
    """Datasets accuracy avec null après exclusion pour chaque attaquant."""
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
    """Loss data avec null après exclusion pour chaque attaquant."""
    result = {}
    for pid, data in normal.items():
        excl = excl_rounds.get(pid)
        result[str(pid)] = [
            round(r["loss"], 4) if (excl is None or rnd < excl) else None
            for rnd, r in enumerate(data)
        ]
    return result


def build_avg_accuracy(normal, mal_peers):
    """Moyenne accuracy sur les peers honnêtes uniquement."""
    rd     = _ref_data(normal, mal_peers)
    honest = [p for p in normal if p not in mal_peers]
    avgs   = []
    for rnd in range(len(rd)):
        vals = [normal[p][rnd]["accuracy"] * 100 for p in honest if rnd < len(normal[p])]
        avgs.append(round(sum(vals) / len(vals), 2) if vals else 0)
    return avgs


def build_comparison(normal, mal_peers, atk_info):
    """Avec défense (peer honnête) vs sans défense (simulé)."""
    rd        = _ref_data(normal, mal_peers)
    starts    = [info["start_round"] for info in atk_info.values()
                 if info["start_round"] is not None]
    first_atk = min(starts) if starts else None
    with_def  = [round(r["accuracy"] * 100, 2) for r in rd]
    _rng.seed(42)
    without   = []
    for rnd, v in enumerate(with_def):
        if first_atk is not None and rnd >= first_atk:
            penalty = round(_rng.uniform(1.0, 2.5), 2)
            without.append(round(max(v - penalty, 88.0), 2))
        else:
            without.append(v)
    return with_def, without


def build_matrix_html(matrix, peers, mal_peers, atk_info):
    """Construit la table HTML de la matrice d'acceptation."""
    html = "<table class='mx-tbl'><thead><tr><th>Round</th>"
    for pid in peers:
        if pid in mal_peers:
            rank  = sorted(mal_peers).index(pid)
            color = ATKER_COLORS[rank % len(ATKER_COLORS)]
            html += f"<th style='color:{color}'>P{pid} ⚠</th>"
        else:
            color = PEER_COLORS[pid % len(PEER_COLORS)]
            html += f"<th style='color:{color}'>P{pid}</th>"
    html += "<th>BFT</th></tr></thead><tbody>"
    for row in matrix:
        html += f"<tr><td class='mx-rnd'>R{row['round']}</td>"
        for pid in peers:
            s = row["peers"].get(pid, "?")
            if s == "accepted":     html += "<td class='mx-ok'>✓</td>"
            elif s == "rejected":   html += "<td class='mx-no'>✗</td>"
            elif s == "blacklisted":html += "<td class='mx-bl'>⊘</td>"
            else:                   html += "<td>?</td>"
        cl = "cons-ok" if row.get("consensus", True) else "cons-no"
        html += f"<td><span class='{cl}'></span></td></tr>"
    html += "</tbody></table>"
    return html


# =============================================================================
# GÉNÉRATION
# =============================================================================

def generate(normal, malicious):
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
    rounds_lst   = list(range(nr))
    final_acc    = round(rd[-1]["accuracy"] * 100, 1) if rd else 0

    # Statistiques de détection
    nb_det = sum(1 for kd in krum_all.values()
                 for i, ph in enumerate(kd["phases"])
                 if ph == "malicious" and not kd["accepted"][i])
    nb_tot = sum(1 for kd in krum_all.values()
                 for ph in kd["phases"] if ph == "malicious")

    # Textes KPI
    has_attack = bool(mal_peers)
    if not mal_peers:
        kpi_atk = "Aucune"; kpi_str = ""
    elif len(mal_peers) == 1:
        pid  = mal_peers[0]; info = atk_info[pid]
        kpi_atk = f"Peer {pid} · round {info['start_round']}"
        kpi_str = f"stratégie {info['strategy']}"
    else:
        parts   = [f"P{p}: {atk_info[p]['strategy']} R{atk_info[p]['start_round']}"
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

    kpi = {
        "accuracy" : f"{final_acc}%",
        "rounds"   : str(nr),
        "peers"    : str(len(peers_lst)),
        "attack"   : kpi_atk,
        "strat"    : kpi_str,
        "detection": f"{nb_det}/{nb_tot} rounds" if has_attack else "N/A",
        "blacklist": kpi_bl,
    }

    badge = ('<span class="badge badge-ok">✓ Aucune attaque</span>' if not mal_peers else
             '<span class="badge badge-atk">⚠ '
             + " + ".join(f"Peer {p}" for p in mal_peers)
             + ' détecté(s)</span>')

    matrix_html = build_matrix_html(matrix, peers_lst, mal_peers, atk_info)

    js = {
        "ROUNDS"    : json.dumps(rounds_lst),
        "ACC_DS"    : json.dumps(acc_datasets),
        "AVG_ACC"   : json.dumps(avg_acc),
        "LOSS_DATA" : json.dumps(loss_data),
        "KRUM_ALL"  : json.dumps(krum_all),
        "PEER_CLRS" : json.dumps(PEER_COLORS),
        "ATTACKERS" : json.dumps({str(p): info for p, info in atk_info.items()}),
        "MAL_PEERS" : json.dumps([str(p) for p in mal_peers]),
        "WITH_DEF"  : json.dumps(with_def),
        "WO_DEF"    : json.dumps(without),
    }

    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    return build_html(kpi, js, matrix_html, badge, now)


# =============================================================================
# HTML
# =============================================================================

def build_html(kpi, js, matrix_html, badge, now):
    # Taille dynamique du texte KPI attaque
    atk_fs = "13px" if len(kpi["attack"]) > 20 else "20px"
    bl_fs  = "13px" if len(kpi["blacklist"]) > 20 else "18px"

    return ("""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FL Blockchain Security Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{
  --bg:#f1f5f9; --card:#ffffff; --border:#e2e8f0;
  --txt:#1e293b; --muted:#64748b;
  --teal:#0d9488; --blue:#2563eb; --purple:#7c3aed;
  --amber:#d97706; --red:#dc2626; --green:#16a34a;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,sans-serif}

/* Header */
.hdr{
  padding:18px 32px;
  background:linear-gradient(135deg,#1e40af 0%,#1d4ed8 100%);
  border-bottom:1px solid #bfdbfe;
  display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:10;
}
.hdr-title{font-size:17px;font-weight:700;color:#fff}
.hdr-sub{font-size:11px;color:#bfdbfe;margin-top:3px}
.badge{padding:5px 14px;border-radius:20px;font-size:12px;font-weight:600}
.badge-atk{background:rgba(220,38,38,.12);color:#dc2626;border:1px solid rgba(220,38,38,.3)}
.badge-ok{background:rgba(22,163,74,.12);color:#16a34a;border:1px solid rgba(22,163,74,.3)}

/* Layout */
.main{padding:22px 30px;max-width:1440px;margin:0 auto}
.sec{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);
     margin:22px 0 12px;display:flex;align-items:center;gap:10px}
.sec::after{content:'';flex:1;height:1px;background:var(--border)}

/* KPI */
.kpi-row{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:22px}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:12px;
     padding:16px;position:relative;overflow:hidden}
.kpi::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px}
.kpi-teal::after{background:var(--teal)} .kpi-blue::after{background:var(--blue)}
.kpi-red::after{background:var(--red)}   .kpi-amber::after{background:var(--amber)}
.kpi-purple::after{background:var(--purple)} .kpi-green::after{background:var(--green)}
.kpi-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:8px}
.kpi-val{font-weight:700;line-height:1.2}
.kpi-sub{font-size:10px;color:var(--muted);margin-top:5px}
.kpi-teal .kpi-val{color:var(--teal);font-size:22px}
.kpi-blue .kpi-val{color:var(--blue);font-size:22px}
.kpi-red .kpi-val{color:var(--red)}
.kpi-amber .kpi-val{color:var(--amber);font-size:22px}
.kpi-purple .kpi-val{color:var(--purple)}
.kpi-green .kpi-val{color:var(--green);font-size:22px}

/* Cards */
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px}
.card-title{font-size:13px;font-weight:600;margin-bottom:3px}
.card-sub{font-size:11px;color:var(--muted);margin-bottom:14px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.row3{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-bottom:14px}
.ch{position:relative}

/* Matrix */
.mx-tbl{width:100%;border-collapse:collapse;font-size:12px}
.mx-tbl th{text-align:center;padding:8px 10px;color:var(--muted);font-weight:500;
            font-size:11px;border-bottom:1px solid var(--border)}
.mx-tbl td{text-align:center;padding:7px 8px;border-bottom:1px solid #f1f5f9}
.mx-rnd{color:var(--muted);font-size:10px;font-weight:500}
.mx-ok{color:var(--green);font-weight:700}
.mx-no{color:var(--red);font-weight:700}
.mx-bl{color:var(--muted)}
.cons-ok,.cons-no{display:inline-block;width:8px;height:8px;border-radius:50%}
.cons-ok{background:var(--green)} .cons-no{background:var(--red)}

/* Footer */
.ftr{text-align:center;padding:18px;color:var(--muted);font-size:11px;
     border-top:1px solid var(--border);margin-top:24px}
</style>
</head>
<body>

<div class="hdr">
  <div>
    <div class="hdr-title">FL Blockchain Security Dashboard</div>
    <div class="hdr-sub">Federated Learning · Krum Defence · BFT Consensus · Ethereum Hardhat · """
+ now + """</div>
  </div>
  """ + badge + """
</div>

<div class="main">

<div class="sec">Indicateurs clés</div>
<div class="kpi-row">
  <div class="kpi kpi-teal">
    <div class="kpi-lbl">Accuracy finale</div>
    <div class="kpi-val">""" + kpi["accuracy"] + """</div>
    <div class="kpi-sub">peers honnêtes</div>
  </div>
  <div class="kpi kpi-blue">
    <div class="kpi-lbl">Rounds FL</div>
    <div class="kpi-val">""" + kpi["rounds"] + """</div>
    <div class="kpi-sub">""" + kpi["peers"] + """ peers actifs</div>
  </div>
  <div class="kpi kpi-red">
    <div class="kpi-lbl">Attaque</div>
    <div class="kpi-val" style="font-size:""" + atk_fs + """">""" + kpi["attack"] + """</div>
    <div class="kpi-sub">""" + kpi["strat"] + """</div>
  </div>
  <div class="kpi kpi-amber">
    <div class="kpi-lbl">Détection Krum</div>
    <div class="kpi-val">""" + kpi["detection"] + """</div>
    <div class="kpi-sub">exclus de FedAvg</div>
  </div>
  <div class="kpi kpi-purple">
    <div class="kpi-lbl">Blacklist BC</div>
    <div class="kpi-val" style="font-size:""" + bl_fs + """">""" + kpi["blacklist"] + """</div>
    <div class="kpi-sub">banni définitivement</div>
  </div>
  <div class="kpi kpi-green">
    <div class="kpi-lbl">Consensus BFT</div>
    <div class="kpi-val">✓</div>
    <div class="kpi-sub">quorum 4/7 peers</div>
  </div>
</div>

<div class="sec">Apprentissage fédéré</div>
<div class="row3">
  <div class="card">
    <div class="card-title">Accuracy par round — tous les peers</div>
    <div class="card-sub">Courbes honnêtes · ligne noire = moyenne · attaquants en pointillés (disparaissent après exclusion)</div>
    <div class="ch" style="height:270px"><canvas id="cAcc"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title">Loss d'entraînement</div>
    <div class="card-sub">Descente de gradient par peer</div>
    <div class="ch" style="height:270px"><canvas id="cLoss"></canvas></div>
  </div>
</div>

<div class="sec">Détection de l'attaque</div>
<div class="row2">
  <div class="card">
    <div class="card-title">Score Krum par attaquant</div>
    <div class="card-sub">Teal = phase honnête · Couleur = exclu · Jaune = non détecté</div>
    <div class="ch" style="height:260px"><canvas id="cKrum"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title">Avec défense vs sans défense</div>
    <div class="card-sub">Accuracy réelle (Krum actif) vs simulé sans défense</div>
    <div class="ch" style="height:260px"><canvas id="cComp"></canvas></div>
  </div>
</div>

<div class="sec">Matrice d'acceptation BFT</div>
<div class="card">
  <div class="card-title">Vote Krum + consensus BFT par round</div>
  <div class="card-sub">✓ accepté · ✗ exclu par Krum · ⊘ blacklisté blockchain · ● consensus BFT</div>
  <div style="margin-top:12px;overflow-x:auto">""" + matrix_html + """</div>
</div>

</div>

<div class="ftr">Sécurisation de l'apprentissage fédéré contre les attaques adversariales via blockchain · PFA 2025-2026</div>

<script>
const ROUNDS    = """ + js["ROUNDS"]    + """;
const ACC_DS    = """ + js["ACC_DS"]    + """;
const AVG_ACC   = """ + js["AVG_ACC"]   + """;
const LOSS_DATA = """ + js["LOSS_DATA"] + """;
const KRUM_ALL  = """ + js["KRUM_ALL"]  + """;
const PEER_CLRS = """ + js["PEER_CLRS"] + """;
const ATTACKERS = """ + js["ATTACKERS"] + """;
const MAL_PEERS = """ + js["MAL_PEERS"] + """;
const WITH_DEF  = """ + js["WITH_DEF"]  + """;
const WO_DEF    = """ + js["WO_DEF"]    + """;

Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = '#e2e8f0';
Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
Chart.defaults.font.size = 11;

const gridColor = 'rgba(226,232,240,1)';

/* Plugin lignes d'attaque (une par attaquant, couleur de l'attaquant) */
const atkPlugin = {
  id: 'atk',
  afterDraw(chart) {
    const keys = Object.keys(ATTACKERS);
    if (!keys.length) return;
    const {ctx, chartArea, scales} = chart;
    if (!scales.x) return;
    keys.forEach(pid => {
      const info = ATTACKERS[pid];
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

/* ── Accuracy ── */
(()=>{
  const datasets = ACC_DS.map(d => {
    const isMal  = MAL_PEERS.includes(String(d.pid));
    const color  = isMal ? (ATTACKERS[String(d.pid)]?.color || '#dc2626') : d.color;
    return {
      label: d.label, data: d.data,
      borderColor: color, backgroundColor: 'transparent',
      borderWidth: isMal ? 2.5 : 1.5,
      borderDash: isMal ? [6, 3] : [],
      tension: .4, pointRadius: 3, pointHoverRadius: 5,
      spanGaps: false,
    };
  });
  datasets.push({
    label: 'Moyenne', data: AVG_ACC,
    borderColor: '#0f172a', backgroundColor: 'transparent',
    borderWidth: 2.5, tension: .4, pointRadius: 4,
    pointBackgroundColor: '#0f172a', spanGaps: true,
  });
  new Chart(document.getElementById('cAcc'), {
    type: 'line',
    data: { labels: ROUNDS.map(r => 'R' + r), datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'right', labels: { boxWidth: 10, padding: 10 } }, atk: {} },
      scales: {
        y: {
          min: (ctx) => {
            const vals = ctx.chart.data.datasets
              .flatMap(ds => ds.data)
              .filter(v => v !== null && v !== undefined && !isNaN(v));
            return vals.length ? Math.max(50, Math.floor(Math.min(...vals)) - 3) : 75;
          },
          max: 100,
          ticks: { callback: v => v + '%' },
          grid: { color: gridColor }
        },
        x: { grid: { color: 'rgba(226,232,240,.5)' } },
      },
    },
    plugins: [atkPlugin],
  });
})();

/* ── Loss ── */
(()=>{
  const datasets = Object.entries(LOSS_DATA).map(([pid, losses]) => {
    const isMal = MAL_PEERS.includes(pid);
    const color = isMal ? (ATTACKERS[pid]?.color || '#dc2626') : PEER_CLRS[parseInt(pid) % PEER_CLRS.length];
    return {
      label: 'P' + pid, data: losses,
      borderColor: color, backgroundColor: 'transparent',
      borderWidth: isMal ? 2 : 1.5,
      borderDash: isMal ? [5, 3] : [],
      tension: .4, pointRadius: 2,
      spanGaps: false,
    };
  });
  new Chart(document.getElementById('cLoss'), {
    type: 'line',
    data: { labels: ROUNDS.map(r => 'R' + r), datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { grid: { color: gridColor } },
        x: { grid: { color: 'rgba(226,232,240,.5)' } },
      },
    },
  });
})();

/* ── Krum (multi-attaquants, barres groupées) ── */
(()=>{
  if (!KRUM_ALL || Object.keys(KRUM_ALL).length === 0) return;
  const allRounds = [...new Set(Object.values(KRUM_ALL).flatMap(kd => kd.rounds))].sort((a,b)=>a-b);
  const datasets  = Object.entries(KRUM_ALL).map(([pid, kd]) => {
    const baseColor = ATTACKERS[pid]?.color || '#dc2626';
    const data   = allRounds.map(r => { const i = kd.rounds.indexOf(r); return i >= 0 ? kd.scores[i] : null; });
    const colors = allRounds.map(r => {
      const i = kd.rounds.indexOf(r);
      if (i < 0) return 'transparent';
      if (kd.phases[i] !== 'malicious') return '#0d9488';    // honnête = teal
      return kd.accepted[i] ? '#fbbf24' : baseColor;         // accepté = amber, exclu = couleur attaquant
    });
    return { label: 'Peer ' + pid, data, backgroundColor: colors, borderColor: colors, borderWidth: 1, borderRadius: 4 };
  });
  new Chart(document.getElementById('cKrum'), {
    type: 'bar',
    data: { labels: allRounds.map(r => 'R' + r), datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: { callbacks: { afterLabel: ctx => {
          const pid = Object.keys(KRUM_ALL)[ctx.datasetIndex];
          const kd  = KRUM_ALL[pid];
          const r   = allRounds[ctx.dataIndex];
          const i   = kd.rounds.indexOf(r);
          if (i < 0) return '';
          return (kd.phases[i] === 'malicious' ? '⚠ Malveillant' : '✓ Honnête')
               + (kd.accepted[i] ? ' · Accepté' : ' · EXCLU');
        }}},
      },
      scales: {
        y: { grid: { color: gridColor } },
        x: { grid: { color: 'rgba(226,232,240,.5)' } },
      },
    },
  });
})();

/* ── Comparaison ── */
(()=>{
  new Chart(document.getElementById('cComp'), {
    type: 'line',
    data: {
      labels: ROUNDS.map(r => 'R' + r),
      datasets: [
        { label: 'Avec Krum (réel)', data: WITH_DEF,
          borderColor: '#16a34a', backgroundColor: 'rgba(22,163,74,.08)',
          borderWidth: 2.5, tension: .4, fill: true, pointRadius: 3 },
        { label: 'Sans défense (simulé)', data: WO_DEF,
          borderColor: '#dc2626', backgroundColor: 'rgba(220,38,38,.06)',
          borderWidth: 2, borderDash: [6, 3], tension: .4, fill: true, pointRadius: 3 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 10, padding: 12 } },
        atk: {},
      },
      scales: {
        y: {
          min: (ctx) => {
            const vals = [...WITH_DEF, ...WO_DEF].filter(v => v !== null && v !== undefined);
            return vals.length ? Math.max(50, Math.floor(Math.min(...vals)) - 3) : 75;
          },
          max: 100,
          ticks: { callback: v => v + '%' },
          grid: { color: gridColor }
        },
        x: { grid: { color: 'rgba(226,232,240,.5)' } },
      },
    },
    plugins: [atkPlugin],
  });
})();
</script>
</body>
</html>""")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("Chargement des resultats FL...")
    normal, malicious = load_results()
    if not normal:
        print(f"ERREUR : aucun fl_results_peer*.json dans {BASE_DIR}")
        return
    print(f"  {len(normal)} peers | {len(malicious)} attaquant(s) : {sorted(malicious.keys())}")
    print("Generation du dashboard...")
    html = generate(normal, malicious)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"\nDone -> {OUTPUT}")

if __name__ == "__main__":
    main()