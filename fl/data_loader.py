# fl/data_loader.py — Chargement et partitionnement du dataset NSL-KDD

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder, StandardScaler
from torch.utils.data import Dataset, DataLoader
import torch

from config import DATA_PATH, NUM_PEERS


# Colonnes NSL-KDD (41 features + label + difficulty)
COLUMNS = [
    "duration", "protocol_type", "service", "flag", "src_bytes", "dst_bytes",
    "land", "wrong_fragment", "urgent", "hot", "num_failed_logins",
    "logged_in", "num_compromised", "root_shell", "su_attempted", "num_root",
    "num_file_creations", "num_shells", "num_access_files", "num_outbound_cmds",
    "is_host_login", "is_guest_login", "count", "srv_count", "serror_rate",
    "srv_serror_rate", "rerror_rate", "srv_rerror_rate", "same_srv_rate",
    "diff_srv_rate", "srv_diff_host_rate", "dst_host_count",
    "dst_host_srv_count", "dst_host_same_srv_rate", "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate", "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate", "dst_host_srv_serror_rate", "dst_host_rerror_rate",
    "dst_host_srv_rerror_rate", "label", "difficulty"
]

CATEGORICAL_COLS = ["protocol_type", "service", "flag"]


class KDDDataset(Dataset):
    def __init__(self, X: np.ndarray, y: np.ndarray):
        self.X = torch.tensor(X, dtype=torch.float32)
        self.y = torch.tensor(y, dtype=torch.float32).unsqueeze(1)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


def load_and_partition(peer_id: int, batch_size: int = 32):
    """
    Charge NSL-KDD, encode, normalise, et retourne le DataLoader
    de la partition correspondant à peer_id.

    Partitionnement horizontal : chaque peer reçoit 1/NUM_PEERS des données.
    """
    df = pd.read_csv(DATA_PATH, header=None, names=COLUMNS)
    df.drop(columns=["difficulty"], inplace=True)

    # Encodage catégoriel
    for col in CATEGORICAL_COLS:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col].astype(str))

    # Label binaire : normal=0, attaque=1
    df["label"] = (df["label"].str.strip() != "normal").astype(int)

    X = df.drop(columns=["label"]).values.astype(np.float32)
    y = df["label"].values.astype(np.float32)

    # Normalisation
    scaler = StandardScaler()
    X = scaler.fit_transform(X)

    # Partitionnement
    n = len(X)
    chunk = n // NUM_PEERS
    start = peer_id * chunk
    end = start + chunk if peer_id < NUM_PEERS - 1 else n

    X_peer = X[start:end]
    y_peer = y[start:end]

    dataset = KDDDataset(X_peer, y_peer)
    loader  = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    print(f"[Peer {peer_id}] Dataset chargé : {len(dataset)} échantillons")
    return loader


def load_test_set(batch_size: int = 256) -> DataLoader:
    """
    Charge KDDTest+.txt avec le meme pretraitement que KDDTrain+.
    Encodeurs et scaler fittés sur TRAIN uniquement, appliqués sur TEST.
    """
    test_path = DATA_PATH.replace("KDDTrain+.txt", "KDDTest+.txt")

    train_df = pd.read_csv(DATA_PATH, header=None, names=COLUMNS)
    test_df  = pd.read_csv(test_path,  header=None, names=COLUMNS)

    train_df.drop(columns=["difficulty"], inplace=True)
    test_df.drop(columns=["difficulty"],  inplace=True)

    # Fit sur TRAIN, apply sur TEST (pas de data leakage)
    for col in CATEGORICAL_COLS:
        le = LabelEncoder()
        le.fit(train_df[col].astype(str))
        train_df[col] = le.transform(train_df[col].astype(str))
        test_df[col]  = test_df[col].apply(
            lambda x: le.transform([str(x)])[0] if str(x) in le.classes_ else 0
        )

    train_df["label"] = (train_df["label"].str.strip() != "normal").astype(int)
    test_df["label"]  = (test_df["label"].str.strip()  != "normal").astype(int)

    feat_cols = [c for c in COLUMNS if c not in ("label", "difficulty")]

    X_train = train_df[feat_cols].values.astype(np.float32)
    X_test  = test_df[feat_cols].values.astype(np.float32)
    y_test  = test_df["label"].values.astype(np.float32)

    scaler = StandardScaler()
    scaler.fit(X_train)
    X_test = scaler.transform(X_test)

    dataset = KDDDataset(X_test, y_test)
    print(f"[Test set] {len(dataset)} echantillons charges depuis {test_path}")
    return DataLoader(dataset, batch_size=batch_size, shuffle=False)