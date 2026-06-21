#!/usr/bin/env python3
# start_fl.py — Lanceur unique FL Blockchain pour Windows et Linux/WSL

import argparse
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE_DIR       = Path(__file__).parent.resolve()
BLOCKCHAIN_DIR = BASE_DIR / "blockchain"
FL_DIR         = BASE_DIR / "fl"
LOGS_DIR       = BASE_DIR / "logs"

NUM_PEERS    = 7
HARDHAT_HOST = "127.0.0.1"
HARDHAT_PORT = 8545

ALL_PROCS = []
RUN_PLATFORM = "auto"


def detect_platform() -> str:
    """Retourne windows ou linux. WSL est traité comme linux."""
    if RUN_PLATFORM != "auto":
        return RUN_PLATFORM

    system = platform.system().lower()
    if system == "windows":
        return "windows"

    return "linux"


def kill_port(port=8545):
    """Libère le port Hardhat selon l'OS courant."""
    os_mode = detect_platform()
    try:
        if os_mode == "windows":
            r = subprocess.run(
                f'netstat -ano | findstr ":{port} "',
                shell=True, capture_output=True, text=True,
            )
            pids = set()
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and f":{port}" in parts[1]:
                    pids.add(parts[4])
            for pid in pids:
                if pid.isdigit() and int(pid) > 0:
                    subprocess.run(
                        f"taskkill /F /PID {pid}",
                        shell=True, capture_output=True,
                    )
        else:
            r = subprocess.run(
                f"lsof -ti tcp:{port}",
                shell=True, capture_output=True, text=True,
            )
            pids = [p for p in r.stdout.split() if p.isdigit()]
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

        if pids:
            print(f"  Port {port} libere (PIDs : {sorted(pids)})")
            time.sleep(2)
    except Exception as e:
        print(f"  (kill_port info: {e})")


def kill_all():
    """Tue tous les processus lancés par ce script."""
    os_mode = detect_platform()
    print("\nFermeture de tous les processus...", flush=True)

    if os_mode == "windows":
        for proc in ALL_PROCS:
            try:
                subprocess.run(
                    f"taskkill /F /T /PID {proc.pid}",
                    shell=True, capture_output=True,
                )
            except Exception:
                pass
    else:
        for proc in ALL_PROCS:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(1)
        for proc in ALL_PROCS:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    kill_port(HARDHAT_PORT)
    print("Termine.", flush=True)


def wait_for_port(host, port, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def pipe_output(proc, tag, log_path):
    with open(log_path, "w", encoding="utf-8", errors="replace") as f:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            print(f"[{tag}] {line}", flush=True)
            f.write(line + "\n")
            f.flush()


def start_bg(cmd, cwd, tag, log_path):
    popen_kwargs = {
        "shell": True,
        "cwd": str(cwd),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }

    if detect_platform() == "windows":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["preexec_fn"] = os.setsid

    proc = subprocess.Popen(cmd, **popen_kwargs)
    ALL_PROCS.append(proc)
    t = threading.Thread(target=pipe_output, args=(proc, tag, log_path), daemon=True)
    t.start()
    return proc


def sep(c="=", n=60):
    print(c * n)


def step1_start_node():
    sep()
    print("[1/3]  Demarrage du noeud Hardhat...")
    sep("-")

    print(f"       Plateforme detectee : {detect_platform()}")
    print("       Liberation du port 8545...")
    kill_port(HARDHAT_PORT)

    proc = start_bg(
        cmd="npx hardhat node",
        cwd=BLOCKCHAIN_DIR,
        tag="HARDHAT",
        log_path=LOGS_DIR / "hardhat_node.log",
    )

    print(f"       Attente port {HARDHAT_PORT}", end="", flush=True)
    for _ in range(45):
        if wait_for_port(HARDHAT_HOST, HARDHAT_PORT, timeout=1):
            print(" OK")
            break
        print(".", end="", flush=True)
        time.sleep(1)
    else:
        print("\nERREUR : noeud Hardhat non disponible.")
        kill_all()
        sys.exit(1)

    time.sleep(2)
    return proc


def step2_deploy():
    sep()
    print("[2/3]  Deploiement de FLGradientRegistry...")
    sep("-")

    result = subprocess.run(
        "npx hardhat run scripts/deploy.js --network localhost",
        shell=True,
        cwd=str(BLOCKCHAIN_DIR),
        capture_output=True,
        text=True,
    )

    with open(LOGS_DIR / "deploy.log", "w", encoding="utf-8") as f:
        f.write(result.stdout + result.stderr)

    if result.returncode != 0:
        print(f"ERREUR deploiement :\n{result.stderr}")
        kill_all()
        sys.exit(1)

    print(result.stdout.strip())

    config_path = BASE_DIR / "blockchain_config.json"
    if not config_path.exists():
        print("ERREUR : blockchain_config.json introuvable !")
        kill_all()
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        addr = json.load(f)["contract_address"]
    print(f"       Contrat : {addr}")


def step2b_clean_previous_run():
    """Nettoie les fichiers générés par les anciens runs."""
    sep()
    print("[2b]  Nettoyage des anciens resultats...")
    sep("-")

    bl = LOGS_DIR / "blacklist_state.json"
    if bl.exists():
        bl.unlink()
        print("       blacklist_state.json supprime")

    for f in BASE_DIR.glob("fl_results_peer*_malicious.json"):
        f.unlink()
        print(f"       {f.name} supprime")

    for f in BASE_DIR.glob("fl_results_peer*.json"):
        f.unlink()
        print(f"       {f.name} supprime")

    print("       Nettoyage termine")


def step3_launch_peers(attackers: dict):
    """attackers = {peer_id: {"strategy": str, "start_round": int}}"""
    sep()
    print(f"[3/3]  Lancement de {NUM_PEERS} peers FL...")
    if attackers:
        for pid, cfg in attackers.items():
            print(
                f"       Peer {pid} MALVEILLANT "
                f"(strategy={cfg['strategy']}, round>={cfg['start_round']})"
            )
    else:
        print("       Mode : tous les peers honnetes")
    sep("-")

    peer_procs = []
    for peer_id in range(NUM_PEERS):
        log_path = LOGS_DIR / f"peer{peer_id}_run.log"

        if peer_id in attackers:
            cfg = attackers[peer_id]
            cmd = (
                f'"{sys.executable}" malicious_peer.py {peer_id} '
                f"--start-round {cfg['start_round']} --strategy {cfg['strategy']}"
            )
            tag = f"MAL{peer_id}"
        else:
            cmd = f'"{sys.executable}" peer.py {peer_id}'
            tag = f"P{peer_id}  "

        proc = start_bg(cmd=cmd, cwd=FL_DIR, tag=tag, log_path=log_path)
        peer_procs.append(proc)
        print(f"       Peer {peer_id} lance (PID {proc.pid:6d})  -> logs/{log_path.name}")
        time.sleep(0.4)

    return peer_procs


def parse_attackers(args) -> dict:
    attackers = {}
    for spec in args.attackers:
        try:
            parts = spec.split(":")
            pid = int(parts[0])
            strat = parts[1] if len(parts) > 1 else "flip"
            sr = int(parts[2]) if len(parts) > 2 else 4
            if 0 <= pid < NUM_PEERS:
                attackers[pid] = {"strategy": strat, "start_round": sr}
            else:
                print(f"ATTENTION : peer ignore hors limite : {pid}")
        except Exception as e:
            print(f"ERREUR parsing attaquant '{spec}' : {e}")

    if args.malicious is not None and args.malicious not in attackers:
        attackers[args.malicious] = {
            "strategy": args.strategy,
            "start_round": args.start_round,
        }

    return attackers


def main():
    global RUN_PLATFORM

    parser = argparse.ArgumentParser(description="Lanceur FL Blockchain")
    parser.add_argument(
        "--platform",
        choices=["auto", "windows", "linux"],
        default="auto",
        help="Force la plateforme si l'auto-détection ne suffit pas. WSL utilise linux.",
    )
    parser.add_argument(
        "--malicious", type=int, default=None, metavar="PEER_ID",
        help="Un seul attaquant, ex: --malicious 3",
    )
    parser.add_argument(
        "--strategy", type=str, default="flip",
        choices=["scale", "flip", "boost", "noise"],
    )
    parser.add_argument("--start-round", type=int, default=4)
    parser.add_argument(
        "--attackers", nargs="+", default=[], metavar="ID:STRATEGY:ROUND",
        help="Multi-attaquants, ex: --attackers 3:flip:3 5:scale:4",
    )
    args = parser.parse_args()
    RUN_PLATFORM = args.platform

    attackers = parse_attackers(args)
    LOGS_DIR.mkdir(exist_ok=True)

    sep()
    print("   FL BLOCKCHAIN - Lanceur automatique")
    print(f"   Projet : {BASE_DIR}")
    print(f"   OS     : {detect_platform()}")
    sep()
    print()

    try:
        step1_start_node()
        step2_deploy()
        step2b_clean_previous_run()
        peer_procs = step3_launch_peers(attackers)

        sep()
        print("   Tous les peers sont actifs - Ctrl+C pour arreter")
        sep()
        print()

        for proc in peer_procs:
            proc.wait()

        print()
        sep()
        print("   Tous les peers ont termine !")
        print(f"   Resultats : {BASE_DIR}/fl_results_peer*.json")
        sep()

    except KeyboardInterrupt:
        kill_all()


if __name__ == "__main__":
    main()
