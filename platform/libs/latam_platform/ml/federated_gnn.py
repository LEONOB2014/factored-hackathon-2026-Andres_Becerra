"""Federated graph learning across country silos (residency-preserving training).

Each country's customer subgraph (fgl_silo_nodes / fgl_silo_edges) stays in its residency region; only
model weights travel. Clients train a 2-layer GraphSAGE on their bipartite customer-merchant graph to
predict `label_complaint_90d`; the server aggregates with FedAvg (weighted by client size) and optional
DP-FedAvg (per-client update clipping + Gaussian noise). Compared against local-only and centralised
training so the cost of federation is measured, not assumed. In production the same loop runs on Flower
with secure aggregation; this is the single-process simulation used for evaluation.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd

FEATURES = [
    "credit_score",
    "tenure_days",
    "tx_count",
    "log_amount_usd",
    "decline_rate",
    "n_merchants",
]


def _silo_graph(nodes: pd.DataFrame, edges: pd.DataFrame, silo: str):
    import torch
    from torch_geometric.data import Data

    n = nodes[nodes.silo == silo].sort_values("local_idx")
    e = edges[edges.silo == silo]
    x = n[FEATURES].astype("float32").fillna(0).to_numpy()
    x = (x - x.mean(0)) / (x.std(0) + 1e-6)
    x = np.hstack([x, (n.node_type == "merchant").to_numpy(np.float32)[:, None]])
    ei = np.vstack([np.r_[e.src_idx, e.dst_idx], np.r_[e.dst_idx, e.src_idx]])  # undirected
    y = n.label_complaint_90d.fillna(False).astype(int).to_numpy()
    is_cust = (n.node_type == "customer").to_numpy()
    rng = np.random.default_rng(0)
    test = is_cust & (rng.random(len(n)) < 0.3)
    return Data(
        x=torch.tensor(x),
        edge_index=torch.tensor(ei, dtype=torch.long),
        y=torch.tensor(y),
        train_mask=torch.tensor(is_cust & ~test),
        test_mask=torch.tensor(test),
    )


def _model(in_dim: int):
    import torch
    from torch_geometric.nn import SAGEConv

    class Sage(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.c1, self.c2, self.out = (
                SAGEConv(in_dim, 32),
                SAGEConv(32, 32),
                torch.nn.Linear(32, 1),
            )

        def forward(self, x, ei):
            return self.out(torch.relu(self.c2(torch.relu(self.c1(x, ei)), ei))).view(-1)

    return Sage()


def _train_local(model, g, epochs: int, pos_weight: float):
    import torch

    opt = torch.optim.Adam(model.parameters(), lr=0.01)
    lossf = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_weight))
    for _ in range(epochs):
        opt.zero_grad()
        out = model(g.x, g.edge_index)
        loss = lossf(out[g.train_mask], g.y[g.train_mask].float())
        loss.backward()
        opt.step()
    return model


def _auc(model, g) -> float:
    import torch
    from sklearn.metrics import roc_auc_score

    with torch.no_grad():
        p = model(g.x, g.edge_index)[g.test_mask].sigmoid().numpy()
    y = g.y[g.test_mask].numpy()
    return float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else float("nan")


def run_federation(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    rounds: int = 20,
    local_epochs: int = 3,
    dp_clip: float | None = None,
    dp_noise_multiplier: float = 0.0,
    seed: int = 0,
) -> dict:
    import torch

    torch.manual_seed(seed)
    silos = sorted(nodes.silo.unique())
    graphs = {s: _silo_graph(nodes, edges, s) for s in silos}
    in_dim = next(iter(graphs.values())).x.size(1)
    pos_rate = float(nodes.label_complaint_90d.fillna(False).mean())
    pw = (1 - pos_rate) / max(pos_rate, 1e-6)

    local = {
        s: _auc(_train_local(_model(in_dim), g, rounds * local_epochs, pw), g)
        for s, g in graphs.items()
    }

    glob = _model(in_dim)
    sizes = {s: int(g.train_mask.sum()) for s, g in graphs.items()}
    for _ in range(rounds):
        states, weights = [], []
        for s, g in graphs.items():
            m = _train_local(copy.deepcopy(glob), g, local_epochs, pw)
            delta = {k: m.state_dict()[k] - glob.state_dict()[k] for k in glob.state_dict()}
            if dp_clip:  # DP-FedAvg: clip the client update ...
                norm = torch.sqrt(sum((d.float() ** 2).sum() for d in delta.values()))
                scale = min(1.0, dp_clip / (float(norm) + 1e-12))
                delta = {k: d * scale for k, d in delta.items()}
            states.append(delta)
            weights.append(sizes[s])
        w = np.array(weights, dtype=float) / sum(weights)
        new = {}
        for k, v in glob.state_dict().items():
            agg = sum(wi * st[k] for wi, st in zip(w, states))
            if dp_clip and dp_noise_multiplier > 0:  # ... and add Gaussian noise to the aggregate
                agg = agg + torch.randn_like(agg.float()) * dp_noise_multiplier * dp_clip / len(
                    states
                )
            new[k] = v + agg
        glob.load_state_dict(new)
    federated = {s: _auc(glob, g) for s, g in graphs.items()}

    # centralised baseline (what federation is trying to approximate without moving data)
    import torch_geometric.utils as U
    from torch_geometric.data import Batch

    union = Batch.from_data_list(list(graphs.values()))
    central = _train_local(_model(in_dim), union, rounds * local_epochs, pw)
    centralised = {s: _auc(central, g) for s, g in graphs.items()}
    _ = U
    return {
        "silos": silos,
        "silo_sizes": sizes,
        "auc_local_only": local,
        "auc_federated": federated,
        "auc_centralised": centralised,
        "rounds": rounds,
        "local_epochs": local_epochs,
        "dp": {"clip": dp_clip, "noise_multiplier": dp_noise_multiplier},
        "positive_rate": pos_rate,
    }
