"""Temporal Graph Network (Rossi et al., 2020) on the customer -> merchant transaction stream.

Task: self-supervised future-link prediction (does customer u transact with merchant v at time t?), the
standard TGN objective. Customer memory embeddings learned this way are reusable features for fraud, churn
and AML once real labels exist. Fraud labels are NOT used for training (they encode the legacy score).
Input: lake/graph/tgn_tx_events.parquet (dense disjoint ids, time-ordered, out-of-time split).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def train_tgn(
    events: pd.DataFrame,
    epochs: int = 2,
    memory_dim: int = 64,
    embedding_dim: int = 64,
    batch_size: int = 500,
    seed: int = 0,
) -> dict:
    import torch
    from sklearn.metrics import average_precision_score, roc_auc_score
    from torch_geometric.data import TemporalData
    from torch_geometric.loader import TemporalDataLoader
    from torch_geometric.nn import TGNMemory, TransformerConv
    from torch_geometric.nn.models.tgn import IdentityMessage, LastAggregator, LastNeighborLoader

    torch.manual_seed(seed)
    ev = events.sort_values("ts").reset_index(drop=True)
    msg = torch.tensor(
        ev[
            [
                "log_amount",
                "is_cross_border",
                "is_night",
                "tx_count_24h",
                "amount_zscore_vs_history",
            ]
        ]
        .fillna(0)
        .to_numpy(np.float32)
    )
    data = TemporalData(
        src=torch.tensor(ev.src.to_numpy()),
        dst=torch.tensor(ev.dst.to_numpy()),
        t=torch.tensor(ev.ts.to_numpy(np.int64)),
        msg=msg,
    )
    n_nodes = int(max(ev.src.max(), ev.dst.max())) + 1
    split = ev.split.to_numpy()
    is_train = torch.tensor(split == "train")
    tr, te = data[is_train], data[~is_train]  # time-ordered: train strictly precedes test
    dst_pool = torch.tensor(np.unique(ev.dst.to_numpy()))

    class Embed(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.time_enc = torch.nn.Linear(1, 16)
            self.conv = TransformerConv(
                memory_dim, embedding_dim // 2, heads=2, dropout=0.1, edge_dim=msg.size(1) + 16
            )

        def forward(self, x, last_update, edge_index, t, m):
            rel_t = (last_update[edge_index[0]] - t).float().view(-1, 1) / 86400.0
            return self.conv(x, edge_index, torch.cat([torch.cos(self.time_enc(rel_t)), m], dim=-1))

    class LinkPred(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.l1, self.l2 = (
                torch.nn.Linear(embedding_dim * 2, embedding_dim),
                torch.nn.Linear(embedding_dim, 1),
            )

        def forward(self, zs, zd):
            return self.l2(torch.relu(self.l1(torch.cat([zs, zd], dim=-1))))

    memory = TGNMemory(
        n_nodes,
        msg.size(1),
        memory_dim,
        16,
        IdentityMessage(msg.size(1), memory_dim, 16),
        LastAggregator(),
    )
    gnn, head = Embed(), LinkPred()
    opt = torch.optim.Adam(
        set(memory.parameters()) | set(gnn.parameters()) | set(head.parameters()), lr=1e-3
    )
    neighbor_loader = LastNeighborLoader(n_nodes, size=10)
    assoc = torch.empty(n_nodes, dtype=torch.long)
    bce = torch.nn.BCEWithLogitsLoss()

    def step(batch, train: bool):
        neg = dst_pool[torch.randint(0, len(dst_pool), (batch.num_events,))]
        n_id, edge_index, e_id = neighbor_loader(torch.cat([batch.src, batch.dst, neg]).unique())
        assoc[n_id] = torch.arange(n_id.size(0))
        z, last_update = memory(n_id)
        if edge_index.numel():
            z = gnn(z, last_update, edge_index, data.t[e_id], data.msg[e_id])
        pos = head(z[assoc[batch.src]], z[assoc[batch.dst]])
        negs = head(z[assoc[batch.src]], z[assoc[neg]])
        memory.update_state(batch.src, batch.dst, batch.t, batch.msg)
        neighbor_loader.insert(batch.src, batch.dst)
        return pos, negs

    history = []
    for epoch in range(epochs):
        memory.reset_state()
        neighbor_loader.reset_state()
        memory.train()
        gnn.train()
        head.train()
        total = 0.0
        for batch in TemporalDataLoader(tr, batch_size=batch_size):
            opt.zero_grad()
            pos, neg = step(batch, True)
            loss = bce(pos, torch.ones_like(pos)) + bce(neg, torch.zeros_like(neg))
            loss.backward()
            opt.step()
            memory.detach()
            total += loss.item() * batch.num_events
        history.append(total / tr.num_events)

    memory.eval()
    gnn.eval()
    head.eval()
    ys, ps = [], []
    with torch.no_grad():
        for batch in TemporalDataLoader(te, batch_size=batch_size):
            pos, neg = step(batch, False)
            ps += torch.cat([pos, neg]).sigmoid().view(-1).tolist()
            ys += [1] * pos.size(0) + [0] * neg.size(0)
    return {
        "train_loss": history,
        "test_link_ap": float(average_precision_score(ys, ps)),
        "test_link_auc": float(roc_auc_score(ys, ps)),
        "train_events": int(tr.num_events),
        "test_events": int(te.num_events),
        "nodes": n_nodes,
    }
